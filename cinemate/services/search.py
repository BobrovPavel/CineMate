"""Movie search through TMDB with an in-process response cache."""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.models import Movie, Rating, User
from cinemate.tmdb import TmdbClient, TmdbSearchItem

CACHE_MAX_ENTRIES = 1000
CACHE_TTL_SECONDS = 24 * 3600


class SearchCache:
    """Thread-safe LRU cache with a time-to-live; keys are ``(query, language, page)``."""

    def __init__(
        self,
        max_entries: int = CACHE_MAX_ENTRIES,
        ttl: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_entries
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._data: OrderedDict[tuple, tuple[float, list[TmdbSearchItem]]] = OrderedDict()

    def get(self, key: tuple) -> list[TmdbSearchItem] | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            stored_at, items = entry
            if self._clock() - stored_at >= self._ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return items

    def put(self, key: tuple, items: list[TmdbSearchItem]) -> None:
        with self._lock:
            self._data[key] = (self._clock(), items)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


@dataclass(frozen=True)
class SearchResult:
    item: TmdbSearchItem
    movie_id: int | None
    user_value: int | None


def search_movies(
    session: Session,
    client: TmdbClient,
    cache: SearchCache,
    user: User,
    query: str,
    language: str,
    page: int = 1,
) -> list[SearchResult]:
    """TMDB results for ``query`` (cached), annotated with our movie id and the user's rating.

    ``TmdbError`` from the client propagates; failures are not cached.
    """
    key = (" ".join(query.lower().split()), language, page)
    items = cache.get(key)
    if items is None:
        items = client.search(query.strip(), language, page)
        cache.put(key, items)
    movies: dict[tuple[str, int], int] = {}
    ids = {item.tmdb_id for item in items}
    if ids:
        rows = session.execute(
            select(Movie.tmdb_type, Movie.tmdb_id, Movie.id).where(Movie.tmdb_id.in_(ids))
        )
        movies = {(t, tid): mid for t, tid, mid in rows}
    values: dict[int, int] = {}
    if movies:
        rated = session.execute(
            select(Rating.movie_id, Rating.value).where(
                Rating.user_id == user.id, Rating.movie_id.in_(set(movies.values()))
            )
        )
        values = {movie_id: value for movie_id, value in rated}
    results = []
    for item in items:
        movie_id = movies.get((item.tmdb_type, item.tmdb_id))
        results.append(SearchResult(item, movie_id, values.get(movie_id) if movie_id else None))
    return results
