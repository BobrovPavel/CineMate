"""Refresh movie metadata (titles, overview, poster, runtime) from TMDB into the database."""

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session

from cinemate.db.catalog import CatalogConflict, link
from cinemate.db.details import apply_extended
from cinemate.db.features import apply_features
from cinemate.db.models import Movie, Rating
from cinemate.db.text import fit
from cinemate.tmdb import DEFAULT_WORKERS, TmdbClient, TmdbDetails, fetch_many

DEFAULT_STALE_DAYS = 30
DEFAULT_CATALOG_STALE_DAYS = 150
MAX_STALE_DAYS = 180  # TMDB terms: stored data must not be kept longer than 6 months
BATCH_SIZE = 1000  # movies loaded, requested, written and committed at a time
PROGRESS_EVERY = 1000  # records between two progress lines
RATED_GROUP = "фильмы с оценками"
REST_GROUP = "остальной каталог"
MAX_FAILURE_LINES = 20
# errors of writing one movie: the savepoint is rolled back and the movie counts as failed
SAVEPOINT_ERRORS = (DataError, IntegrityError)


@dataclass(frozen=True)
class EnrichStats:
    enriched: int
    not_found: int
    skipped: int = 0
    failed: int = 0


def apply_details(session: Session, movie: Movie, details: TmdbDetails) -> None:
    """Overwrite ``movie`` fields with TMDB values; an empty value never erases a stored one.

    TMDB genres replace the stored ones (see ``apply_features``), the collection, companies,
    countries, original language and vote are written, ``tmdb_fetched_at`` is set and the IMDb id
    is linked. Strings are cut to the length of their column (see ``cinemate.db.text.fit``).
    """
    for field, value in (
        ("title", details.title),
        ("original_title", details.original_title),
        ("title_ru", details.title_ru),
        ("year", details.year),
        ("overview", details.overview_ru or details.overview),
        ("poster_path", details.poster_path),
        ("runtime", details.runtime),
    ):
        if value:
            setattr(movie, field, fit(getattr(Movie, field), value))
    movie.tmdb_fetched_at = datetime.now(UTC)
    apply_features(session, movie, details)
    if details.extended:
        apply_extended(session, movie, details)
    else:
        for field, value in (
            ("budget", details.budget),
            ("revenue", details.revenue),
            ("tagline", details.tagline),
            ("number_of_seasons", details.number_of_seasons),
            ("number_of_episodes", details.number_of_episodes),
        ):
            if value:
                setattr(movie, field, fit(getattr(Movie, field), value))
    if details.imdb_id:
        try:
            with session.begin_nested():
                link(session, movie, "imdb", details.imdb_id)
        except CatalogConflict:
            pass  # the imdb id belongs to another movie; keep the pair as the key


class FailureReporter:
    """Reports movies that could not be written, at most ``MAX_FAILURE_LINES`` lines."""

    def __init__(self, report: Callable[[str], None] | None):
        self._report = report
        self.count = 0

    def __call__(self, movie_id: int | None, pair: tuple[str, int], exc: Exception) -> None:
        self.count += 1
        if self._report is None or self.count > MAX_FAILURE_LINES:
            return
        shown = f"movie id {movie_id}, " if movie_id is not None else ""
        self._report(f"failed: {shown}TMDB {pair[0]} {pair[1]}: {type(exc).__name__}")
        if self.count == MAX_FAILURE_LINES:
            self._report("further failures are not listed")


@dataclass(frozen=True)
class _Pass:
    """One selection of movies: ``where`` and the sort key (before ``Movie.id``)."""

    where: ColumnElement[bool]
    key: InstrumentedAttribute | None = None
    group: str | None = None  # name of the pass shown in the progress lines


def _passes(
    cutoff: datetime,
    catalog_cutoff: datetime,
    extended: bool,
    missing_features: bool,
    refresh_titles: bool,
) -> list[_Pass]:
    rated = select(Rating.id).where(Rating.movie_id == Movie.id).exists()
    if extended:
        stale = Movie.details_fetched_at < cutoff
        return [
            _Pass(rated & Movie.details_fetched_at.is_(None)),
            _Pass(rated & stale, Movie.details_fetched_at),
        ]
    if missing_features:
        todo = Movie.tmdb_vote_count.is_(None)
        return [_Pass(todo & rated), _Pass(todo & ~rated)]
    if refresh_titles:
        return [_Pass((Movie.title_ru.is_(None)) | (Movie.title_ru == ""))]
    fetched = Movie.tmdb_fetched_at
    return [
        _Pass(rated & fetched.is_(None), None, RATED_GROUP),
        _Pass(
            rated
            & fetched.is_not(None)
            & ((fetched < cutoff) | (Movie.details_fetched_at < cutoff)),
            fetched,
            RATED_GROUP,
        ),
        _Pass(~rated & fetched.is_(None), None, REST_GROUP),
        _Pass(
            ~rated
            & fetched.is_not(None)
            & ((fetched < catalog_cutoff) | (Movie.details_fetched_at < catalog_cutoff)),
            fetched,
            REST_GROUP,
        ),
    ]


def _page(session: Session, selection: _Pass, last: tuple | None, size: int) -> list[tuple]:
    """Next ``size`` keys ``(id, tmdb_type, tmdb_id, details_fetched_at, sort_key)`` after
    ``last`` (the ``(sort_key, id)`` of the previous page)."""
    has_pair = Movie.tmdb_id.is_not(None) & Movie.tmdb_type.is_not(None)
    key = selection.key
    columns = [Movie.id, Movie.tmdb_type, Movie.tmdb_id, Movie.details_fetched_at]
    if key is not None:
        columns.append(key)
    query = select(*columns).where(has_pair, selection.where)
    if key is None:
        if last is not None:
            query = query.where(Movie.id > last[1])
        query = query.order_by(Movie.id)
    else:
        if last is not None:
            query = query.where(or_(key > last[0], and_(key == last[0], Movie.id > last[1])))
        query = query.order_by(key, Movie.id)
    return [tuple(row) for row in session.execute(query.limit(size))]


def enrich_movies(
    session: Session,
    client: TmdbClient,
    limit: int | None = None,
    refresh_titles: bool = False,
    stale_days: int = DEFAULT_STALE_DAYS,
    catalog_stale_days: int = DEFAULT_CATALOG_STALE_DAYS,
    missing_features: bool = False,
    workers: int = DEFAULT_WORKERS,
    extended: bool = False,
    report: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> EnrichStats:
    """Re-fetch TMDB details for movies with a TMDB pair whose data is stale.

    Stale means ``tmdb_fetched_at`` is ``NULL`` or older than ``stale_days`` (1..180) for movies
    with ratings in any pool, and older than ``catalog_stale_days`` (1..180) for the rest of the
    catalog; extended data (``details_fetched_at``) is refreshed by the same term. Two passes, the
    rated movies first, in each the ``NULL`` ones go first, then the oldest. With
    ``refresh_titles`` only movies without ``title_ru`` are requested, whatever their age.
    Details come from
    ``client.fetch_details(tmdb_type, tmdb_id)``, ``workers`` requests at a time (the database is
    written by the calling thread only); fields are overwritten with TMDB values but an
    empty TMDB value never erases a stored one, TMDB genres replace the old ones, the IMDb id is
    linked. With ``missing_features`` only movies that never got their features (no TMDB vote
    count) are requested, whatever their age: first those with ratings in any pool, then the rest.
    With ``extended`` only movies with ratings in any pool whose extended data (credits,
    keywords, age rating, budget...) is missing or stale are requested, with ``extended=True``;
    it excludes ``refresh_titles`` and ``missing_features``. Without it, movies that already have
    extended data are refreshed with it when it is stale; the others get the basic data only.
    A 404 leaves the movie untouched (``not_found``). ``skipped`` counts movies without a TMDB
    pair. ``limit`` caps the number of movies requested.

    Movies are processed in batches of ``BATCH_SIZE``: only their keys are selected page by page
    (keyset on the sort key and ``id``), the ``Movie`` objects of one batch are loaded, its details
    fetched in parallel and written, the batch committed and the session cleared, so time and
    memory per movie do not depend on the size of the selection. A database error
    (``DataError``, ``IntegrityError``) on one movie rolls back its savepoint and counts it as
    ``failed``; a ``TmdbError`` (or Ctrl+C) stops the run, finished batches and the movies written
    so far stay committed and a repeated run goes on with the rest. ``report`` receives progress
    lines (the number to process, every ``PROGRESS_EVERY`` records, failures).
    """
    if not 1 <= stale_days <= MAX_STALE_DAYS:
        raise ValueError(f"stale_days must be between 1 and {MAX_STALE_DAYS}")
    if not 1 <= catalog_stale_days <= MAX_STALE_DAYS:
        raise ValueError(f"catalog_stale_days must be between 1 and {MAX_STALE_DAYS}")
    if extended and (refresh_titles or missing_features):
        raise ValueError("extended cannot be combined with refresh_titles or missing_features")
    has_pair = Movie.tmdb_id.is_not(None) & Movie.tmdb_type.is_not(None)
    skipped = session.scalar(select(func.count()).select_from(Movie).where(~has_pair)) or 0

    cutoff = datetime.now(UTC) - timedelta(days=stale_days)
    catalog_cutoff = datetime.now(UTC) - timedelta(days=catalog_stale_days)
    passes = _passes(cutoff, catalog_cutoff, extended, missing_features, refresh_titles)
    budget = limit
    counts: list[int] = []
    for selection in passes:
        found = (
            session.scalar(select(func.count()).select_from(Movie).where(has_pair, selection.where))
            or 0
        )
        if budget is not None:
            found = min(found, budget)
            budget -= found
        counts.append(found)
    total = sum(counts)
    say = report or (lambda line: None)
    say(f"к обработке: {total}")
    if missing_features:
        say(f"из них с оценками: {counts[0]}")
    if passes[0].group is not None:
        for group in dict.fromkeys(p.group for p in passes):
            n = sum(c for p, c in zip(passes, counts, strict=True) if p.group == group)
            say(f"проход «{group}»: {n}")

    enriched = not_found = 0
    failures = FailureReporter(report)
    started = clock()

    def processed() -> int:
        return enriched + not_found + failures.count

    def progress() -> None:
        done = processed()
        elapsed = clock() - started
        rate = done / elapsed if elapsed > 0 else 0.0
        left = f", about {int((total - done) / rate // 60)} min left" if rate > 0 else ""
        say(
            f"processed {done}/{total}, {rate:.1f}/s{left} "
            f"({enriched} enriched, {not_found} not found, {failures.count} failed)"
        )

    try:
        for selection, wanted in zip(passes, counts, strict=True):
            last: tuple | None = None
            while wanted > 0:
                keys = _page(session, selection, last, min(BATCH_SIZE, wanted))
                if not keys:
                    break
                wanted -= len(keys)
                last = (keys[-1][4] if selection.key is not None else None, keys[-1][0])
                by_pair = {(k[1], k[2]): k[0] for k in keys}
                wants_extended = {(k[1], k[2]) for k in keys if extended or k[3] is not None}
                movies = {
                    m.id: m
                    for m in session.scalars(select(Movie).where(Movie.id.in_(by_pair.values())))
                }
                try:
                    with contextlib.closing(
                        fetch_many(client, by_pair, workers, wants_extended)
                    ) as fetched:
                        for pair, details in fetched:
                            if details is None:
                                not_found += 1
                            else:
                                movie = movies[by_pair[pair]]
                                try:
                                    with session.begin_nested():
                                        apply_details(session, movie, details)
                                except SAVEPOINT_ERRORS as exc:
                                    failures(movie.id, pair, exc)
                                else:
                                    enriched += 1
                            if processed() % PROGRESS_EVERY == 0:
                                progress()
                finally:
                    session.commit()
                    session.expunge_all()
    finally:
        session.commit()
    if processed() % PROGRESS_EVERY != 0:
        progress()
    return EnrichStats(enriched, not_found, skipped, failures.count)
