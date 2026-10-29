"""Movie features: genres (one TMDB dictionary), collection, companies, countries, language, vote.

Genres are read and written only through ``movie_genres``. Movies with a TMDB pair get TMDB
genres; the rest get the genres translated from MovieLens/Kinopoisk names.
"""

from collections.abc import Iterable, Sequence

from sqlalchemy import Engine, delete, insert, select
from sqlalchemy.orm import Session

from cinemate.db.models import Collection, Company, Genre, MovieCompany, MovieGenre
from cinemate.genres import GENRES, legacy_genre_ids, tmdb_genre_ids
from cinemate.tmdb import TmdbDetails

QUERY_CHUNK = 10_000


def seed_genres(engine: Engine) -> None:
    """Insert the genres missing from the ``genres`` table (migrations do the same)."""
    with engine.begin() as connection:
        known = set(connection.scalars(select(Genre.id)))
        rows = [
            {"id": g.id, "name_en": g.name_en, "name_ru": g.name_ru}
            for g in GENRES
            if g.id not in known
        ]
        if rows:
            connection.execute(insert(Genre), rows)


def set_movie_genres(session: Session, movie_id: int, genre_ids: Iterable[int]) -> None:
    """Replace the genres of the movie with ``genre_ids``."""
    ids = sorted(set(genre_ids))
    session.execute(delete(MovieGenre).where(MovieGenre.movie_id == movie_id))
    if ids:
        session.execute(insert(MovieGenre), [{"movie_id": movie_id, "genre_id": g} for g in ids])


def has_genres(session: Session, movie_id: int) -> bool:
    return (
        session.scalar(select(MovieGenre.genre_id).where(MovieGenre.movie_id == movie_id))
        is not None
    )


def set_legacy_genres(session: Session, movie, names: Sequence[str]) -> None:
    """Set the genres of a movie from MovieLens/Kinopoisk ``names``.

    Movies whose data came from TMDB keep their TMDB genres.
    """
    if movie.tmdb_fetched_at is not None:
        return
    if movie.id is None:
        session.flush()
    set_movie_genres(session, movie.id, legacy_genre_ids(names)[0])


def genre_ids_by_movie(session: Session, movie_ids: Sequence[int]) -> dict[int, list[int]]:
    """Genre ids (ascending) of each movie that has any."""
    result: dict[int, list[int]] = {}
    for start in range(0, len(movie_ids), QUERY_CHUNK):
        chunk = movie_ids[start : start + QUERY_CHUNK]
        query = (
            select(MovieGenre.movie_id, MovieGenre.genre_id)
            .where(MovieGenre.movie_id.in_(chunk))
            .order_by(MovieGenre.movie_id, MovieGenre.genre_id)
        )
        for movie_id, genre_id in session.execute(query):
            result.setdefault(movie_id, []).append(genre_id)
    return result


def genre_names_by_movie(
    session: Session, movie_ids: Sequence[int], language: str
) -> dict[int, list[str]]:
    """Genre names of each movie in ``language`` (``ru`` or English), ordered by genre id."""
    names = {
        g.id: (g.name_ru if language == "ru" else g.name_en) for g in session.scalars(select(Genre))
    }
    return {
        movie_id: [names[g] for g in ids if g in names]
        for movie_id, ids in genre_ids_by_movie(session, movie_ids).items()
    }


def apply_features(session: Session, movie, details: TmdbDetails) -> None:
    """Write the TMDB features of ``details`` to ``movie`` (a stored value is erased only by
    a TMDB answer that has the field: genres keep their old value when TMDB sends none).
    """
    if movie.id is None:
        session.flush()
    ids = tmdb_genre_ids(details.genre_ids)
    if ids:
        set_movie_genres(session, movie.id, ids)

    if details.collection is not None:
        collection_id, name = details.collection
        collection = session.get(Collection, collection_id)
        if collection is None:
            session.add(Collection(id=collection_id, name=name))
        else:
            collection.name = name
        movie.collection_id = collection_id
    else:
        movie.collection_id = None

    wanted: dict[int, tuple[str, str | None]] = {c[0]: (c[1], c[2]) for c in details.companies}
    for company_id, (name, logo_path) in wanted.items():
        company = session.get(Company, company_id)
        if company is None:
            session.add(Company(id=company_id, name=name, logo_path=logo_path))
        else:
            company.name = name
            company.logo_path = logo_path or company.logo_path
    session.flush()
    session.execute(delete(MovieCompany).where(MovieCompany.movie_id == movie.id))
    if wanted:
        session.execute(
            insert(MovieCompany), [{"movie_id": movie.id, "company_id": c} for c in wanted]
        )

    movie.countries = list(details.countries)
    if details.original_language:
        movie.original_language = details.original_language
    if details.vote_average is not None:
        movie.tmdb_vote_average = details.vote_average
    if details.vote_count is not None:
        movie.tmdb_vote_count = details.vote_count
