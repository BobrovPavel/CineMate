"""Movie search: through TMDB with an in-process response cache, or in our own catalog."""

import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import and_, case, func, literal_column, or_, select
from sqlalchemy.orm import Session, sessionmaker

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


SEARCH_SOURCES = ("auto", "local", "tmdb")
LOCAL_CATALOG_MIN_SIZE = 100_000
CATALOG_CHECK_SECONDS = 3600
LOCAL_PAGE_SIZE = 20

_NON_WORD = re.compile(r"[\W_]+")


def normalize_query(query: str) -> str:
    """Lower case, ``ё`` -> ``е``, punctuation and repeated spaces collapsed to one space."""
    return _NON_WORD.sub(" ", query.lower().replace("ё", "е")).strip()


def resolve_search_source(
    value: str | None = None, environ: Mapping[str, str] | None = None
) -> str:
    """Search source: argument -> env ``SEARCH_SOURCE`` -> ``auto``; ``ValueError`` if unknown."""
    if value is None:
        env = os.environ if environ is None else environ
        value = env.get("SEARCH_SOURCE", "")
    value = value.strip().lower() or "auto"
    if value not in SEARCH_SOURCES:
        raise ValueError(f"SEARCH_SOURCE: invalid value {value!r}; use auto, local or tmdb")
    return value


class SearchSelector:
    """Decides whether ``auto`` mode serves searches from our own catalog.

    The catalog counts as ready when it holds at least ``threshold`` movies with a TMDB pair.
    The size is checked by :meth:`refresh` (at startup) and again at most once per ``ttl``
    seconds, never on every search.
    """

    def __init__(
        self,
        mode: str,
        session_factory: sessionmaker[Session],
        threshold: int = LOCAL_CATALOG_MIN_SIZE,
        ttl: float = CATALOG_CHECK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.mode = mode
        self.threshold = threshold
        self._session_factory = session_factory
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._checked_at: float | None = None
        self._ready = False

    def refresh(self) -> bool:
        with self._session_factory() as session:
            count = session.scalar(
                select(func.count()).select_from(Movie).where(Movie.tmdb_id.is_not(None))
            )
        with self._lock:
            self._ready = (count or 0) >= self.threshold
            self._checked_at = self._clock()
            return self._ready

    def catalog_ready(self) -> bool:
        with self._lock:
            fresh = self._checked_at is not None and self._clock() - self._checked_at < self._ttl
            if fresh:
                return self._ready
        return self.refresh()


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Punctuation of titles turned into spaces in SQL, like ``normalize_query`` does for the query.
# Migration 0010 builds its indexes on the same expression: change both together.
_TITLE_PUNCTUATION = "-:.·'’,!?\"()&/;"


def _sql_literal(text: str):
    return literal_column("'" + text.replace("'", "''") + "'")


def _normalized_column(col):
    expr = func.replace(func.lower(col), _sql_literal("ё"), _sql_literal("е"))
    for char in _TITLE_PUNCTUATION:
        expr = func.replace(expr, _sql_literal(char), _sql_literal(" "))
    for _ in range(2):
        expr = func.replace(expr, _sql_literal("  "), _sql_literal(" "))
    return func.trim(expr)


def search_local(
    session: Session,
    query: str,
    page: int = 1,
    page_size: int = LOCAL_PAGE_SIZE,
    language: str = "en-US",
    user: User | None = None,
) -> list[SearchResult]:
    """Search ``title``, ``original_title`` and ``title_ru`` of movies that have a TMDB pair.

    Order: exact title match, then title starting with the query, then the rest (every word of
    the query is a substring; on PostgreSQL, when nothing contains the query, trigram similarity
    instead); inside each group by ``tmdb_popularity`` descending. ``movie_id`` is always set;
    ``user_value`` is filled when ``user`` is given.
    """
    q = normalize_query(query)
    if not q or page < 1 or page_size < 1:
        return []
    names = [_normalized_column(col) for col in (Movie.title, Movie.original_title, Movie.title_ru)]
    esc = "\\"
    tokens = [f"%{_like_escape(t)}%" for t in q.split()]
    # substring / all words: served by the trigram indexes on PostgreSQL
    contains = or_(*(and_(*(n.like(t, escape=esc) for t in tokens)) for n in names))
    exact = or_(*(n == q for n in names))
    prefix = or_(*(n.like(f"{_like_escape(q)}%", escape=esc) for n in names))
    group = case((exact, 0), (prefix, 1), else_=2)
    base = select(Movie).where(Movie.tmdb_id.is_not(None), Movie.tmdb_type.is_not(None))

    def run(match, *order):
        stmt = base.where(match).order_by(group, *order, Movie.tmdb_popularity.desc().nulls_last())
        stmt = stmt.order_by(Movie.id).limit(page_size).offset((page - 1) * page_size)
        return session.scalars(stmt).all()

    rows = run(contains)
    if not rows and page == 1 and session.get_bind().dialect.name == "postgresql":
        # nothing contains the query: fall back to trigram similarity (typos, word order)
        similar = or_(*(n.op("%")(q) for n in names))
        best = func.greatest(*(func.coalesce(func.similarity(n, q), 0) for n in names))
        rows = run(similar, best.desc())
    values: dict[int, int] = {}
    if user is not None and rows:
        rated = session.execute(
            select(Rating.movie_id, Rating.value).where(
                Rating.user_id == user.id, Rating.movie_id.in_([m.id for m in rows])
            )
        )
        values = {movie_id: value for movie_id, value in rated}
    ru = language.lower().startswith("ru")
    return [
        SearchResult(
            TmdbSearchItem(
                m.tmdb_type or "movie",
                m.tmdb_id or 0,
                (m.title_ru if ru and m.title_ru else m.title),
                m.original_title,
                m.year,
                m.poster_path,
            ),
            m.id,
            values.get(m.id),
        )
        for m in rows
    ]


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
