"""Fill movie metadata (overview, poster, runtime) from TMDB into the database."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.models import Movie
from cinemate.tmdb import TmdbClient


@dataclass(frozen=True)
class EnrichStats:
    enriched: int
    not_found: int


def enrich_movies(session: Session, client: TmdbClient, limit: int | None = None) -> EnrichStats:
    """Fetch metadata for movies with a ``tmdb_id`` and an empty ``overview``.

    Movies that already have an overview are not touched. ``limit`` caps the number of
    movies requested. Movies TMDB does not know, or knows without an overview, stay empty
    and are counted as ``not_found``. A ``TmdbError`` propagates after committing progress.
    """
    query = (
        select(Movie)
        .where(Movie.tmdb_id.is_not(None), (Movie.overview.is_(None)) | (Movie.overview == ""))
        .order_by(Movie.id)
    )
    if limit is not None:
        query = query.limit(limit)
    movies = list(session.scalars(query))
    enriched = not_found = 0
    try:
        for movie in movies:
            info = client.fetch_movie(movie.tmdb_id)
            if info is None or not info.overview:
                not_found += 1
                continue
            movie.overview = info.overview
            movie.poster_path = info.poster_path
            movie.runtime = info.runtime
            if info.original_title:
                movie.original_title = info.original_title
            enriched += 1
    finally:
        session.commit()
    return EnrichStats(enriched, not_found)
