"""FastAPI dependencies: a session per request and the shared matrix store."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import User
from cinemate.services.users import get_user_by_token

SESSION_COOKIE = "cinemate_session"


def get_db_session(request: Request) -> Iterator[Session]:
    """Yield a session; commit if the handler succeeds, roll back if it raises."""
    with request.app.state.session_factory() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def get_matrix_store(request: Request) -> MatrixStore:
    """Return the application-wide :class:`MatrixStore`."""
    return request.app.state.matrix_store


def session_token(request: Request) -> str | None:
    """Return the session token from the cookie, if any."""
    return request.cookies.get(SESSION_COOKIE)


def get_current_user(
    request: Request, session: Annotated[Session, Depends(get_db_session)]
) -> User:
    """Resolve the user from the session cookie; ``401`` if absent or unknown."""
    token = session_token(request)
    user = get_user_by_token(session, token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="no valid session")
    return user
