"""In-memory cache of the ratings matrices (one per user pool) loaded from the database."""

import logging
import threading
import time
from collections.abc import Callable
from itertools import chain

import numpy as np
from scipy.sparse import csr_matrix
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.models import DEFAULT_POOL, Rating, User
from cinemate.recommender.matrix import RatingsMatrix

logger = logging.getLogger(__name__)

DEFAULT_REBUILD_SECONDS = 300.0
_LOAD_CHUNK = 200_000


class MatrixStore:
    """Builds a ratings matrix per user pool from the ``ratings`` table and caches it.

    A pool's matrix holds only the ratings of that pool's users. :meth:`get` returns the last
    built matrix; it builds synchronously only on the first use of a pool. :meth:`invalidate`
    marks a pool stale without touching the database: the next :meth:`get` after
    ``rebuild_interval`` seconds since the previous build starts a rebuild in a background
    thread, serves the old matrix meanwhile and swaps in the new one atomically. Callers that
    need their own fresh ratings must read them from the database themselves.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        rebuild_interval: float = DEFAULT_REBUILD_SECONDS,
    ) -> None:
        if rebuild_interval < 0:
            raise ValueError("rebuild_interval must be >= 0")
        self._session_factory = session_factory
        self._rebuild_interval = rebuild_interval
        self._lock = threading.Lock()  # guards the dicts below, never held while loading
        self._cached: dict[str, RatingsMatrix] = {}
        self._built_at: dict[str, float] = {}
        self._stale: set[str] = set()
        self._rebuilding: set[str] = set()
        self._loading: set[str] = set()  # pools inside _build, cached or not yet
        self._first_build_locks: dict[str, threading.Lock] = {}

    def get(self, pool: str = DEFAULT_POOL) -> RatingsMatrix:
        """Return the last built matrix of ``pool``; build it first if the pool is new."""
        with self._lock:
            cached = self._cached.get(pool)
            if cached is not None:
                self._maybe_start_rebuild(pool)
                return cached
            first_lock = self._first_build_locks.setdefault(pool, threading.Lock())
        with first_lock:
            with self._lock:
                cached = self._cached.get(pool)
            if cached is None:
                cached = self._build(pool)
        return cached

    def invalidate(self, pool: str | None = None) -> None:
        """Mark ``pool`` (all cached pools if ``None``) stale; no database access happens here."""
        with self._lock:
            if pool is None:
                self._stale.update(self._cached, self._loading)
            elif pool in self._cached or pool in self._loading:
                self._stale.add(pool)

    def rebuild_now(self, pool: str | None = None) -> None:
        """Synchronously rebuild ``pool`` (every cached pool if ``None``); for tests and tools."""
        with self._lock:
            pools = list(self._cached) if pool is None else [pool]
        for name in pools:
            self._build(name)

    def _maybe_start_rebuild(self, pool: str) -> None:
        """Start a background rebuild if due. Call with ``self._lock`` held."""
        if pool not in self._stale or pool in self._rebuilding:
            return
        if time.monotonic() - self._built_at[pool] < self._rebuild_interval:
            return
        self._rebuilding.add(pool)
        threading.Thread(target=self._background_build, args=(pool,), daemon=True).start()

    def _background_build(self, pool: str) -> None:
        try:
            self._build(pool)
        except Exception:
            logger.exception("background rebuild of the %r ratings matrix failed", pool)
            # keep serving the old matrix; the pool stays stale and is retried after the interval
            with self._lock:
                self._built_at[pool] = time.monotonic()
        finally:
            with self._lock:
                self._rebuilding.discard(pool)

    def _build(self, pool: str) -> RatingsMatrix:
        with self._lock:
            self._stale.discard(pool)  # invalidations that arrive during the load stay marked
            self._loading.add(pool)
        try:
            matrix = self._load(pool)
        except Exception:
            with self._lock:
                self._loading.discard(pool)
                if pool in self._cached:
                    self._stale.add(pool)
            raise
        with self._lock:
            self._loading.discard(pool)
            self._cached[pool] = matrix
            self._built_at[pool] = time.monotonic()
        return matrix

    def _load(self, pool: str) -> RatingsMatrix:
        users, movies, values = [], [], []
        with self._session_factory() as session:
            # the connection, not the ORM session, skips per-row ORM machinery
            result = session.connection().execute(
                select(Rating.user_id, Rating.movie_id, Rating.value)
                .join(User, User.id == Rating.user_id)
                .where(User.pool == pool)
                .execution_options(yield_per=_LOAD_CHUNK)
            )
            for part in result.partitions():
                flat = np.fromiter(chain.from_iterable(part), dtype=np.int64, count=3 * len(part))
                chunk = flat.reshape(-1, 3)
                users.append(chunk[:, 0])
                movies.append(chunk[:, 1])
                values.append(chunk[:, 2].astype(np.int8))
        return matrix_from_arrays(users, movies, values)


def matrix_from_arrays(
    users: list[np.ndarray], movies: list[np.ndarray], values: list[np.ndarray]
) -> RatingsMatrix:
    """Build the matrix from chunks of ``(user, movie, +1/-1)`` columns with unique pairs.

    Ids are sorted ascending, as in :func:`cinemate.recommender.matrix.matrix_from_values`.
    """
    if not users:
        return RatingsMatrix(matrix=csr_matrix((0, 0), dtype=np.int8), user_ids=[], movie_ids=[])
    user_ids, rows = np.unique(np.concatenate(users), return_inverse=True)
    movie_ids, cols = np.unique(np.concatenate(movies), return_inverse=True)
    matrix = csr_matrix(
        (np.concatenate(values), (rows, cols)), shape=(len(user_ids), len(movie_ids))
    )
    return RatingsMatrix(matrix=matrix, user_ids=user_ids.tolist(), movie_ids=movie_ids.tolist())
