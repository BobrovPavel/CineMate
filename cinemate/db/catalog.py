"""Movie catalog: look movies up by any external id, link ids, merge duplicates.

``Movie.id`` is the only key inside the system. A movie is identified outside by the TMDB pair
(``tmdb_type``, ``tmdb_id``) and by ids from other sources kept in ``movie_external_ids``.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cinemate.db.models import Event, Movie, MovieExternalId, Rating, SeenMark
from cinemate.tmdb import TmdbClient

SOURCE_ORDER = ("imdb", "movielens", "kinopoisk", "ratings_csv")

_MOVIE_FIELDS = (
    "imdb_id",
    "original_title",
    "title_ru",
    "year",
    "overview",
    "poster_path",
    "runtime",
)


class CatalogConflict(Exception):
    """An external id is already linked to a different movie."""


def _legacy_ids(movie: Movie) -> list[tuple[str, str]]:
    """Ids kept in the old ``movies.external_*``/``imdb_id`` columns, as (source, id)."""
    pairs = [
        ("movielens", movie.external_movielens_id),
        ("imdb", movie.imdb_id),
        ("kinopoisk", movie.external_kinopoisk_id),
        ("ratings_csv", movie.external_ratings_id),
    ]
    return [(source, str(value)) for source, value in pairs if value is not None]


def find_movie(
    session: Session,
    *,
    tmdb: tuple[str, int] | None = None,
    ids: Mapping[str, str] = {},  # noqa: B006 - never mutated
) -> Movie | None:
    """Find a movie by the TMDB pair first, then by ``ids`` (source -> external id).

    Sources are tried in the order imdb, movielens, kinopoisk, ratings_csv.
    """
    if tmdb is not None:
        movie = session.scalar(
            select(Movie).where(Movie.tmdb_type == tmdb[0], Movie.tmdb_id == tmdb[1])
        )
        if movie is not None:
            return movie
    for source in SOURCE_ORDER:
        external_id = ids.get(source)
        if external_id is None:
            continue
        link = session.get(MovieExternalId, (source, str(external_id)))
        if link is not None:
            return session.get(Movie, link.movie_id)
    return None


def link(session: Session, movie: Movie, source: str, external_id: str | int) -> None:
    """Link ``external_id`` of ``source`` to ``movie``.

    Linking again to the same movie does nothing; an id linked to another movie raises
    ``CatalogConflict`` instead of being silently moved.
    """
    if movie.id is None:
        session.flush()
    existing = session.get(MovieExternalId, (source, str(external_id)))
    if existing is None:
        session.add(MovieExternalId(source=source, external_id=str(external_id), movie_id=movie.id))
        session.flush()
    elif existing.movie_id != movie.id:
        raise CatalogConflict(
            f"{source} id {external_id} is already linked to movie {existing.movie_id}"
        )


def merge_movies(session: Session, keep_id: int, drop_id: int) -> None:
    """Move everything of movie ``drop_id`` to ``keep_id`` and delete ``drop_id``.

    Ratings, seen marks, events and external ids move over; if a user rated (or marked) both,
    the later rating (higher ``created_at``) wins; seen marks have no timestamp, so the one with
    the higher id is taken as the later. Empty fields of the kept movie are filled from the
    dropped one and its popularity is recomputed.
    """
    if keep_id == drop_id:
        raise ValueError("cannot merge a movie into itself")
    keep = session.get(Movie, keep_id)
    drop = session.get(Movie, drop_id)
    if keep is None or drop is None:
        raise ValueError("both movies must exist")

    keep_ratings = {
        r.user_id: r for r in session.scalars(select(Rating).where(Rating.movie_id == keep_id))
    }
    for rating in session.scalars(select(Rating).where(Rating.movie_id == drop_id)).all():
        mine = keep_ratings.get(rating.user_id)
        if mine is None:
            rating.movie_id = keep_id
        else:
            if rating.created_at > mine.created_at:
                mine.value, mine.created_at = rating.value, rating.created_at
            session.delete(rating)

    keep_marks = {
        m.user_id: m for m in session.scalars(select(SeenMark).where(SeenMark.movie_id == keep_id))
    }
    for mark in session.scalars(select(SeenMark).where(SeenMark.movie_id == drop_id)).all():
        mine = keep_marks.get(mark.user_id)
        if mine is None:
            mark.movie_id = keep_id
        elif mark.id > mine.id:
            mine.type = mark.type
            session.delete(mark)
        else:
            session.delete(mark)
    session.flush()

    for source, value in _legacy_ids(drop):
        if session.get(MovieExternalId, (source, value)) is None:
            session.add(MovieExternalId(source=source, external_id=value, movie_id=drop_id))
    session.flush()
    session.execute(update(Event).where(Event.movie_id == drop_id).values(movie_id=keep_id))
    session.execute(
        update(MovieExternalId).where(MovieExternalId.movie_id == drop_id).values(movie_id=keep_id)
    )
    for field in _MOVIE_FIELDS:
        if getattr(keep, field) is None and getattr(drop, field) is not None:
            setattr(keep, field, getattr(drop, field))
    if not keep.genres and drop.genres:
        keep.genres = list(drop.genres)
    if keep.tmdb_id is None and drop.tmdb_id is not None:
        pair = (drop.tmdb_type, drop.tmdb_id)
        # free the pair first: it is unique (uq_movies_tmdb)
        drop.tmdb_type = drop.tmdb_id = None
        session.flush()
        keep.tmdb_type, keep.tmdb_id = pair
    session.flush()
    session.expire_all()

    session.execute(delete(Movie).where(Movie.id == drop_id))
    likes = session.scalar(
        select(func.count())
        .select_from(Rating)
        .where(Rating.movie_id == keep_id, Rating.value == 1)
    )
    session.execute(update(Movie).where(Movie.id == keep_id).values(popularity_score=float(likes)))
    session.flush()
    session.expire_all()


def import_from_tmdb(session: Session, client: TmdbClient, tmdb_type: str, tmdb_id: int) -> Movie:
    """Return the movie with the TMDB pair, creating it from TMDB details if it is not there yet.

    ``title`` is the English title, ``overview`` the Russian one when TMDB has it. If a parallel
    request creates the same pair first (unique ``uq_movies_tmdb``), that movie is returned.
    Raises ``LookupError`` if TMDB does not know the pair and ``TmdbError`` if TMDB fails.
    """
    pair = (tmdb_type, tmdb_id)
    existing = find_movie(session, tmdb=pair)
    if existing is not None:
        return existing
    details = client.fetch_details(tmdb_type, tmdb_id)
    if details is None:
        raise LookupError(f"TMDB has no {tmdb_type} {tmdb_id}")
    movie = Movie(
        tmdb_type=tmdb_type,
        tmdb_id=tmdb_id,
        title=details.title,
        original_title=details.original_title,
        title_ru=details.title_ru,
        year=details.year,
        overview=details.overview_ru or details.overview,
        poster_path=details.poster_path,
        runtime=details.runtime,
        genres=list(details.genres),
        popularity_score=0.0,
        tmdb_fetched_at=datetime.now(UTC),
    )
    try:
        with session.begin_nested():
            session.add(movie)
            session.flush()
    except IntegrityError:
        winner = find_movie(session, tmdb=pair)
        if winner is None:
            raise
        return winner
    if details.imdb_id:
        try:
            with session.begin_nested():
                link(session, movie, "imdb", details.imdb_id)
        except CatalogConflict:
            pass  # the imdb id already belongs to another movie; keep the pair as the key
    return movie
