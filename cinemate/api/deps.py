"""FastAPI dependencies: a session per request and the shared matrix store."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from cinemate.db.matrix_store import MatrixStore


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
