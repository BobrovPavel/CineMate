"""Movie catalog: lookup by external ids, linking and merging duplicates.

``Movie.id`` is the only key used inside the system. A movie is identified outside by the
TMDB pair (``tmdb_type``, ``tmdb_id``) and by rows of ``movie_external_ids``.
"""

from collections.abc import Mapping
from types import MappingProxyType

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from cinemate.db.models import Event, Movie, MovieExternalId, Rating, SeenMark

LOOKUP_ORDER = ("imdb", "movielens", "kinopoisk", "ratings_csv")


class CatalogConflict(Exception):
    """An external id is already linked to another movie."""


def find_movie(
    session: Session,
    *,
    tmdb: tuple[str, int] | None = None,
    ids: Mapping[str, str] = MappingProxyType({}),
) -> Movie | None:
    """Find a movie by its TMDB pair first, then by ``ids`` (source -> external id).

    Sources are tried in the order imdb, movielens, kinopoisk, ratings_csv.
    """
    if tmdb is not None:
        movie = session.scalar(
            select(Movie).where(Movie.tmdb_type == tmdb[0], Movie.tmdb_id == tmdb[1])
        )
        if movie is not None:
            return movie
    for source in LOOKUP_ORDER:
        if source not in ids:
            continue
        movie = session.scalar(
            select(Movie)
            .join(MovieExternalId, MovieExternalId.movie_id == Movie.id)
            .where(
                MovieExternalId.source == source,
                MovieExternalId.external_id == str(ids[source]),
            )
        )
        if movie is not None:
            return movie
    return None


def link(session: Session, movie: Movie, source: str, external_id: str | int) -> None:
    """Attach an external id to ``movie``; raise ``CatalogConflict`` if another movie owns it."""
    if movie.id is None:
        session.flush()
    existing = session.get(MovieExternalId, (source, str(external_id)))
    if existing is None:
        session.add(MovieExternalId(source=source, external_id=str(external_id), movie_id=movie.id))
    elif existing.movie_id != movie.id:
        raise CatalogConflict(
            f"{source} id {external_id} is already linked to movie {existing.movie_id}"
        )


def merge_movies(session: Session, keep_id: int, drop_id: int) -> None:
    """Move everything of movie ``drop_id`` onto ``keep_id`` and delete ``drop_id``.

    Ratings, seen marks, events and external ids are moved. If a user has both movies rated
    (or marked), only the newer rating stays (``created_at``; seen marks have no timestamp,
    so the one with the higher id counts as newer).
    """
    if keep_id == drop_id:
        return
    session.flush()

    kept = {r.user_id: r for r in session.scalars(select(Rating).where(Rating.movie_id == keep_id))}
    for rating in session.scalars(select(Rating).where(Rating.movie_id == drop_id)):
        mine = kept.get(rating.user_id)
        if mine is None:
            rating.movie_id = keep_id
        else:
            if rating.created_at > mine.created_at:
                mine.value, mine.created_at = rating.value, rating.created_at
            session.delete(rating)

    marks = {
        m.user_id: m for m in session.scalars(select(SeenMark).where(SeenMark.movie_id == keep_id))
    }
    for mark in session.scalars(select(SeenMark).where(SeenMark.movie_id == drop_id)):
        mine = marks.get(mark.user_id)
        if mine is None:
            mark.movie_id = keep_id
        else:
            if mark.id > mine.id:
                mine.type = mark.type
            session.delete(mark)
    session.flush()

    session.execute(update(Event).where(Event.movie_id == drop_id).values(movie_id=keep_id))
    session.execute(
        update(MovieExternalId).where(MovieExternalId.movie_id == drop_id).values(movie_id=keep_id)
    )
    dropped = session.get(Movie, drop_id)
    kept_movie = session.get(Movie, keep_id)
    if dropped is not None and kept_movie is not None and kept_movie.tmdb_id is None:
        pair = (dropped.tmdb_type, dropped.tmdb_id)
        dropped.tmdb_type = dropped.tmdb_id = None
        session.flush()
        kept_movie.tmdb_type, kept_movie.tmdb_id = pair
        session.flush()
    session.execute(delete(Movie).where(Movie.id == drop_id))
    session.expire_all()
