"""Refresh movie metadata (titles, overview, poster, runtime) from TMDB into the database."""

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cinemate.db.catalog import CatalogConflict, link
from cinemate.db.details import apply_extended
from cinemate.db.features import apply_features
from cinemate.db.models import Movie, Rating
from cinemate.tmdb import DEFAULT_WORKERS, TmdbClient, TmdbDetails, fetch_many

DEFAULT_STALE_DAYS = 30
MAX_STALE_DAYS = 180  # TMDB terms: stored data must not be kept longer than 6 months
COMMIT_EVERY = 100


@dataclass(frozen=True)
class EnrichStats:
    enriched: int
    not_found: int
    skipped: int = 0


def apply_details(session: Session, movie: Movie, details: TmdbDetails) -> None:
    """Overwrite ``movie`` fields with TMDB values; an empty value never erases a stored one.

    TMDB genres replace the stored ones (see ``apply_features``), the collection, companies,
    countries, original language and vote are written, ``tmdb_fetched_at`` is set and the IMDb id
    is linked.
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
            setattr(movie, field, value)
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
                setattr(movie, field, value)
    if details.imdb_id:
        try:
            with session.begin_nested():
                link(session, movie, "imdb", details.imdb_id)
        except CatalogConflict:
            pass  # the imdb id belongs to another movie; keep the pair as the key


def enrich_movies(
    session: Session,
    client: TmdbClient,
    limit: int | None = None,
    refresh_titles: bool = False,
    stale_days: int = DEFAULT_STALE_DAYS,
    missing_features: bool = False,
    workers: int = DEFAULT_WORKERS,
    extended: bool = False,
) -> EnrichStats:
    """Re-fetch TMDB details for movies with a TMDB pair whose data is stale.

    Stale means ``tmdb_fetched_at`` is ``NULL`` or older than ``stale_days`` (1..180); the
    ``NULL`` ones go first, then the oldest. With ``refresh_titles`` only movies without
    ``title_ru`` are requested, whatever their age. Details come from
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
    pair. ``limit`` caps the number of movies requested; progress is committed every
    ``COMMIT_EVERY`` movies and when a ``TmdbError`` propagates.
    """
    if not 1 <= stale_days <= MAX_STALE_DAYS:
        raise ValueError(f"stale_days must be between 1 and {MAX_STALE_DAYS}")
    if extended and (refresh_titles or missing_features):
        raise ValueError("extended cannot be combined with refresh_titles or missing_features")
    has_pair = Movie.tmdb_id.is_not(None) & Movie.tmdb_type.is_not(None)
    skipped = session.scalar(select(func.count()).select_from(Movie).where(~has_pair)) or 0

    query = select(Movie).where(has_pair)
    cutoff = datetime.now(UTC) - timedelta(days=stale_days)
    if extended:
        rated = select(Rating.id).where(Rating.movie_id == Movie.id).exists()
        query = query.where(
            rated, Movie.details_fetched_at.is_(None) | (Movie.details_fetched_at < cutoff)
        ).order_by(Movie.details_fetched_at.is_not(None), Movie.details_fetched_at, Movie.id)
    elif missing_features:
        rated = select(Rating.id).where(Rating.movie_id == Movie.id).exists()
        query = query.where(Movie.tmdb_vote_count.is_(None)).order_by(~rated, Movie.id)
    elif refresh_titles:
        query = query.where((Movie.title_ru.is_(None)) | (Movie.title_ru == ""))
        query = query.order_by(Movie.id)
    else:
        query = query.where(
            Movie.tmdb_fetched_at.is_(None)
            | (Movie.tmdb_fetched_at < cutoff)
            | (Movie.details_fetched_at < cutoff)
        )
        query = query.order_by(Movie.tmdb_fetched_at.is_not(None), Movie.tmdb_fetched_at, Movie.id)
    if limit is not None:
        query = query.limit(limit)
    movies = list(session.scalars(query))

    enriched = not_found = 0
    try:
        by_pair = {(m.tmdb_type, m.tmdb_id): m for m in movies}
        wants_extended = {
            pair for pair, m in by_pair.items() if extended or m.details_fetched_at is not None
        }
        with contextlib.closing(fetch_many(client, by_pair, workers, wants_extended)) as fetched:
            for pair, details in fetched:
                if details is None:
                    not_found += 1
                    continue
                apply_details(session, by_pair[pair], details)
                enriched += 1
                if enriched % COMMIT_EVERY == 0:
                    session.commit()
    finally:
        session.commit()
    return EnrichStats(enriched, not_found, skipped)
