"""In-memory cache of the ratings matrix loaded from the database."""

import threading
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.models import Rating
from cinemate.recommender.matrix import RatingsMatrix, matrix_from_values


class MatrixStore:
    """Builds the ratings matrix from the ``ratings`` table and caches it.

    The cache is rebuilt only after :meth:`invalidate`; callers are responsible for
    invalidating it when ratings change.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._cached: RatingsMatrix | None = None

    def get(self) -> RatingsMatrix:
        """Return the cached matrix, building it from the database on first use."""
        with self._lock:
            if self._cached is None:
                self._cached = self._load()
            return self._cached

    def invalidate(self) -> None:
        """Drop the cache so the next :meth:`get` reads the database again."""
        with self._lock:
            self._cached = None

    def _load(self) -> RatingsMatrix:
        with self._session_factory() as session:
            rows = session.execute(select(Rating.user_id, Rating.movie_id, Rating.value)).all()
        return matrix_from_values((user, movie, value) for user, movie, value in rows)
