"""Extended TMDB data of a movie: credits, keywords, age rating, budget, revenue, seasons."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from cinemate.db.models import Keyword, Movie, MovieCredit, MovieKeyword, Person
from cinemate.tmdb import DEFAULT_CERTIFICATION_COUNTRY, TmdbClient, TmdbDetails, TmdbError

DEFAULT_STALE_DAYS = 30


def is_stale(movie: Movie, stale_days: int = DEFAULT_STALE_DAYS) -> bool:
    """Extended data was never fetched or is older than ``stale_days``."""
    fetched = movie.details_fetched_at
    if fetched is None:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return fetched < datetime.now(UTC) - timedelta(days=stale_days)


def apply_extended(session: Session, movie: Movie, details: TmdbDetails) -> None:
    """Write the extended data of ``details`` (fetched with ``extended=True``) to ``movie``.

    Credits and keywords are replaced as a whole, so a repeated fetch leaves no duplicates.
    Budget, revenue, tagline, seasons and episodes are overwritten by TMDB values; an empty
    value never erases a stored one.
    """
    if not details.extended:
        raise ValueError("details were fetched without extended=True")
    if movie.id is None:
        session.flush()
    for field, value in (
        ("budget", details.budget),
        ("revenue", details.revenue),
        ("tagline", details.tagline),
        ("number_of_seasons", details.number_of_seasons),
        ("number_of_episodes", details.number_of_episodes),
    ):
        if value:
            setattr(movie, field, value)
    if details.certification is not None:
        movie.certification_country, movie.certification = details.certification

    people = {c.person_id: c for c in details.credits}
    for person_id, credit in people.items():
        person = session.get(Person, person_id)
        if person is None:
            session.add(Person(id=person_id, name=credit.name, profile_path=credit.profile_path))
        else:
            person.name = credit.name
            person.profile_path = credit.profile_path or person.profile_path
    keywords = dict(details.keywords)
    for keyword_id, name in keywords.items():
        keyword = session.get(Keyword, keyword_id)
        if keyword is None:
            session.add(Keyword(id=keyword_id, name=name))
        else:
            keyword.name = name
    session.flush()

    session.execute(delete(MovieCredit).where(MovieCredit.movie_id == movie.id))
    if details.credits:
        session.execute(
            insert(MovieCredit),
            [
                {
                    "movie_id": movie.id,
                    "person_id": c.person_id,
                    "role": c.role,
                    "character": c.character,
                    "ord": c.order,
                }
                for c in details.credits
            ],
        )
    session.execute(delete(MovieKeyword).where(MovieKeyword.movie_id == movie.id))
    if keywords:
        session.execute(
            insert(MovieKeyword), [{"movie_id": movie.id, "keyword_id": k} for k in keywords]
        )
    movie.details_fetched_at = datetime.now(UTC)


def ensure_extended(
    session: Session,
    client: TmdbClient | None,
    movie: Movie,
    certification_country: str = DEFAULT_CERTIFICATION_COUNTRY,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> bool:
    """Fetch the extended data when the movie has none or it is stale (one TMDB request).

    Used when a movie card is opened. Does nothing without a client or a TMDB pair; a TMDB
    error or a 404 leaves the movie as it is. Returns whether new data was stored; the caller
    commits.
    """
    if client is None or movie.tmdb_type is None or movie.tmdb_id is None:
        return False
    if not is_stale(movie, stale_days):
        return False
    from cinemate.db.enrich import apply_details  # enrich imports this module

    try:
        details = client.fetch_details(
            movie.tmdb_type,
            movie.tmdb_id,
            extended=True,
            certification_country=certification_country,
        )
    except TmdbError:
        return False
    if details is None:
        return False
    apply_details(session, movie, details)
    return True
