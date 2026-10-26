"""Fill movie metadata (overview, poster, runtime, Russian title) from TMDB into the database."""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.models import Movie
from cinemate.tmdb import TmdbClient

_CYRILLIC = re.compile("[А-Яа-яЁё]")


@dataclass(frozen=True)
class EnrichStats:
    enriched: int
    not_found: int


def _russian_title(title: str | None) -> str | None:
    """TMDB returns the original title when it has no translation; keep Cyrillic ones only."""
    return title if title and _CYRILLIC.search(title) else None


def enrich_movies(
    session: Session,
    client: TmdbClient,
    limit: int | None = None,
    refresh_titles: bool = False,
) -> EnrichStats:
    """Fetch metadata for movies with a ``tmdb_id`` that have neither overview nor poster.

    Fields are stored independently: a missing overview does not stop the poster, runtime,
    original and Russian titles from being saved. A movie is ``enriched`` when TMDB gave at
    least one of overview, poster or Russian title, otherwise ``not_found``. With
    ``refresh_titles`` only movies without ``title_ru`` are requested and only ``title_ru``
    is written (for movies enriched before it existed). ``limit`` caps the number of movies
    requested. A ``TmdbError`` propagates after committing progress.
    """
    query = select(Movie).where(Movie.tmdb_id.is_not(None))
    if refresh_titles:
        query = query.where((Movie.title_ru.is_(None)) | (Movie.title_ru == ""))
    else:
        query = query.where(
            (Movie.overview.is_(None)) | (Movie.overview == ""),
            (Movie.poster_path.is_(None)) | (Movie.poster_path == ""),
        )
    query = query.order_by(Movie.id)
    if limit is not None:
        query = query.limit(limit)
    movies = list(session.scalars(query))
    enriched = not_found = 0
    try:
        for movie in movies:
            info = client.fetch_movie(movie.tmdb_id)
            if info is None:
                not_found += 1
                continue
            title_ru = _russian_title(info.title)
            if title_ru:
                movie.title_ru = title_ru
            if refresh_titles:
                got = bool(title_ru)
            else:
                got = bool(info.overview or info.poster_path or title_ru)
                if info.overview:
                    movie.overview = info.overview
                if info.poster_path:
                    movie.poster_path = info.poster_path
                if info.runtime:
                    movie.runtime = info.runtime
                if info.original_title:
                    movie.original_title = info.original_title
            if got:
                enriched += 1
            else:
                not_found += 1
    finally:
        session.commit()
    return EnrichStats(enriched, not_found)
