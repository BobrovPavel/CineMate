"""User-facing operations: anonymous sessions, ratings and seen marks.

No web framework is used here. All functions only ``flush`` the session; committing the
transaction is the caller's responsibility.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import DEFAULT_POOL, Movie, Rating, SeenMark, User

SEEN_MARK_TYPES = ("not_seen", "watched", "not_interested")


def pool_from_accept_language(header: str | None) -> str:
    """``'ru'`` if the most preferred language of an ``Accept-Language`` header is Russian.

    Ties on quality go to the language listed first; ``q=0`` entries and malformed
    qualities are ignored. Anything else, including a missing header, gives ``'world'``.
    """
    best_lang, best_q = None, 0.0
    for part in (header or "").split(","):
        lang, *params = (p.strip() for p in part.split(";"))
        if not lang:
            continue
        q = 1.0
        for param in params:
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if q > best_q:
            best_lang, best_q = lang.lower(), q
    if best_lang == "ru" or (best_lang or "").startswith("ru-"):
        return "ru"
    return DEFAULT_POOL


LANGUAGES = ("ru", "en")


def language_from_headers(cookie_lang: str | None, accept_language: str | None) -> str:
    """Interface language: a valid ``cinemate_lang`` cookie wins, else the browser language.

    Returns ``'ru'`` or ``'en'``; the browser language follows the pool rule.
    """
    if cookie_lang in LANGUAGES:
        return cookie_lang
    return "ru" if pool_from_accept_language(accept_language) == "ru" else "en"


def create_session_user(session: Session, pool: str = DEFAULT_POOL) -> User:
    """Create an anonymous user in ``pool`` with a unique random ``session_token``."""
    user = User(session_token=secrets.token_urlsafe(32), is_synthetic=False, pool=pool)
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
    Only flushes; the caller commits. If ``store`` is given, the user's pool cache is dropped.
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
        store.invalidate(user.pool)
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
