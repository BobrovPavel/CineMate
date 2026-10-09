"""Application factory: engine, schema and :class:`MatrixStore` are created once at startup."""

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from cinemate.api.routes import router
from cinemate.cli import resolve_database_url
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.session import create_all, make_engine


def create_app(database_url: str | None = None, cookie_secure: bool = False) -> FastAPI:
    """Build the app; ``database_url`` follows the same resolution rule as the CLI commands.

    ``cookie_secure`` sets the ``Secure`` flag of the session cookie (off for local development).
    """
    engine = make_engine(resolve_database_url(database_url))
    create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False, class_=Session)

    app = FastAPI(title="CineMate")
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.matrix_store = MatrixStore(session_factory)
    app.state.cookie_secure = cookie_secure
    app.include_router(router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
