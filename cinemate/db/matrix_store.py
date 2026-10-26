"""In-memory cache of the ratings matrices (one per user pool) loaded from the database."""

import threading
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.models import DEFAULT_POOL, Rating, User
from cinemate.recommender.matrix import RatingsMatrix, matrix_from_values


class MatrixStore:
    """Builds a ratings matrix per user pool from the ``ratings`` table and caches it.

    A pool's matrix holds only the ratings of that pool's users. A cache entry is rebuilt
    only after :meth:`invalidate`; callers are responsible for invalidating the pool when
    its ratings change.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._cached: dict[str, RatingsMatrix] = {}

    def get(self, pool: str = DEFAULT_POOL) -> RatingsMatrix:
        """Return the cached matrix of ``pool``, building it from the database on first use."""
        with self._lock:
            if pool not in self._cached:
                self._cached[pool] = self._load(pool)
            return self._cached[pool]

    def invalidate(self, pool: str | None = None) -> None:
        """Drop the cache of ``pool`` (all pools if ``None``) so the next read hits the DB."""
        with self._lock:
            if pool is None:
                self._cached.clear()
            else:
                self._cached.pop(pool, None)

    def _load(self, pool: str) -> RatingsMatrix:
        with self._session_factory() as session:
            rows = session.execute(
                select(Rating.user_id, Rating.movie_id, Rating.value)
                .join(User, User.id == Rating.user_id)
                .where(User.pool == pool)
            ).all()
        return matrix_from_values((user, movie, value) for user, movie, value in rows)
