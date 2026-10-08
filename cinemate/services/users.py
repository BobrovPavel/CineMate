"""User-facing operations: anonymous sessions, ratings and seen marks.

No web framework is used here. All functions only ``flush`` the session; committing the
transaction is the caller's responsibility.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, SeenMark, User

SEEN_MARK_TYPES = ("not_seen", "watched", "not_interested")


def create_session_user(session: Session) -> User:
    """Create an anonymous user with a unique random ``session_token``."""
    user = User(session_token=secrets.token_urlsafe(32), is_synthetic=False)
    session.add(user)
    session.flush()
    return user


def get_user_by_token(session: Session, token: str) -> User | None:
    """Return the user owning ``token`` or ``None``."""
    return session.scalar(select(User).where(User.session_token == token))


def _require_movie(session: Session, movie_id: int) -> None:
    if session.get(Movie, movie_id) is None:
        raise LookupError(f"movie {movie_id} not found")


def set_rating(
    session: Session,
    user: User,
    movie_id: int,
    value: int,
    store: MatrixStore | None = None,
) -> Rating:
    """Create or update the user's rating (``+1`` or ``-1``) for a movie.

    Raises ``ValueError`` for any other value and ``LookupError`` for an unknown movie.
    Only flushes; the caller commits. If ``store`` is given its cache is invalidated.
    """
    if isinstance(value, bool) or value not in (1, -1):
        raise ValueError(f"rating value must be +1 or -1, got {value!r}")
    _require_movie(session, movie_id)
    rating = session.scalar(
        select(Rating).where(Rating.user_id == user.id, Rating.movie_id == movie_id)
    )
    if rating is None:
        rating = Rating(user_id=user.id, movie_id=movie_id, value=value)
        session.add(rating)
    else:
        rating.value = value
    session.flush()
    if store is not None:
        store.invalidate()
    return rating


def set_seen_mark(session: Session, user: User, movie_id: int, type: str) -> SeenMark:
    """Create or update the user's seen mark; it never affects the ratings matrix.

    Raises ``ValueError`` for an unknown type and ``LookupError`` for an unknown movie.
    Only flushes; the caller commits.
    """
    if type not in SEEN_MARK_TYPES:
        raise ValueError(f"seen mark type must be one of {SEEN_MARK_TYPES}, got {type!r}")
    _require_movie(session, movie_id)
    mark = session.scalar(
        select(SeenMark).where(SeenMark.user_id == user.id, SeenMark.movie_id == movie_id)
    )
    if mark is None:
        mark = SeenMark(user_id=user.id, movie_id=movie_id, type=type)
        session.add(mark)
    else:
        mark.type = type
    session.flush()
    return mark


def get_ratings(session: Session, user: User) -> list[Rating]:
    """Return all ratings of the user ordered by id (for the profile)."""
    return list(
        session.scalars(select(Rating).where(Rating.user_id == user.id).order_by(Rating.id))
    )
