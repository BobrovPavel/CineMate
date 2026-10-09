"""Session and profile endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from cinemate.api.deps import SESSION_COOKIE, get_current_user, get_db_session, session_token
from cinemate.api.schemas import ProfileItem, SessionOut
from cinemate.db.models import Movie, User
from cinemate.services.users import create_session_user, get_ratings, get_user_by_token

COOKIE_MAX_AGE = 365 * 24 * 3600

router = APIRouter(prefix="/api")


@router.post("/session", response_model=SessionOut)
def open_session(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> SessionOut:
    """Create an anonymous user and set the session cookie, or reuse the one in the cookie."""
    token = session_token(request)
    user = get_user_by_token(session, token) if token else None
    if user is None:
        user = create_session_user(session)
        response.set_cookie(
            SESSION_COOKIE,
            user.session_token or "",
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.app.state.cookie_secure,
        )
    return SessionOut(user_id=user.id)


@router.get("/profile", response_model=list[ProfileItem])
def profile(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ProfileItem]:
    """Ratings of the current user, newest first."""
    items = []
    for rating in reversed(get_ratings(session, user)):
        movie = session.get(Movie, rating.movie_id)
        if movie is None:
            continue
        items.append(
            ProfileItem(
                movie_id=movie.id,
                title=movie.title,
                year=movie.year,
                poster_path=movie.poster_path,
                value=rating.value,
            )
        )
    return items
