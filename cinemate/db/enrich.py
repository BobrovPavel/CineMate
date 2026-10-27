"""Refresh movie metadata (titles, overview, poster, runtime) from TMDB into the database."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cinemate.db.catalog import CatalogConflict, link
from cinemate.db.models import Movie
from cinemate.tmdb import TmdbClient

DEFAULT_STALE_DAYS = 30
MAX_STALE_DAYS = 180  # TMDB terms: stored data must not be kept longer than 6 months
COMMIT_EVERY = 100


@dataclass(frozen=True)
class EnrichStats:
    enriched: int
    not_found: int
    skipped: int = 0


def enrich_movies(
    session: Session,
    client: TmdbClient,
    limit: int | None = None,
    refresh_titles: bool = False,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> EnrichStats:
    """Re-fetch TMDB details for movies with a TMDB pair whose data is stale.

    Stale means ``tmdb_fetched_at`` is ``NULL`` or older than ``stale_days`` (1..180); the
    ``NULL`` ones go first, then the oldest. With ``refresh_titles`` only movies without
    ``title_ru`` are requested, whatever their age. Details come from
    ``client.fetch_details(tmdb_type, tmdb_id)``; fields are overwritten with TMDB values but an
    empty TMDB value never erases a stored one, ``genres`` are left alone, the IMDb id is linked.
    A 404 leaves the movie untouched (``not_found``). ``skipped`` counts movies without a TMDB
    pair. ``limit`` caps the number of movies requested; progress is committed every
    ``COMMIT_EVERY`` movies and when a ``TmdbError`` propagates.
    """
    if not 1 <= stale_days <= MAX_STALE_DAYS:
        raise ValueError(f"stale_days must be between 1 and {MAX_STALE_DAYS}")
    has_pair = Movie.tmdb_id.is_not(None) & Movie.tmdb_type.is_not(None)
    skipped = session.scalar(select(func.count()).select_from(Movie).where(~has_pair)) or 0

    query = select(Movie).where(has_pair)
    if refresh_titles:
        query = query.where((Movie.title_ru.is_(None)) | (Movie.title_ru == ""))
        query = query.order_by(Movie.id)
    else:
        cutoff = datetime.now(UTC) - timedelta(days=stale_days)
        query = query.where(Movie.tmdb_fetched_at.is_(None) | (Movie.tmdb_fetched_at < cutoff))
        query = query.order_by(Movie.tmdb_fetched_at.is_not(None), Movie.tmdb_fetched_at, Movie.id)
    if limit is not None:
        query = query.limit(limit)
    movies = list(session.scalars(query))

    enriched = not_found = 0
    try:
        for movie in movies:
            details = client.fetch_details(movie.tmdb_type, movie.tmdb_id)
            if details is None:
                not_found += 1
                continue
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
            if details.imdb_id:
                try:
                    with session.begin_nested():
                        link(session, movie, "imdb", details.imdb_id)
                except CatalogConflict:
                    pass  # the imdb id belongs to another movie; keep the pair as the key
            enriched += 1
            if enriched % COMMIT_EVERY == 0:
                session.commit()
    finally:
        session.commit()
    return EnrichStats(enriched, not_found, skipped)
