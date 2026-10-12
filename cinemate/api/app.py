"""Application factory: engine, schema and :class:`MatrixStore` are created once at startup."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from cinemate.api.routes import router
from cinemate.cli import resolve_database_url
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.session import create_all, make_engine

DEFAULT_CORS_ORIGINS = ["http://localhost:3000"]


def resolve_cors_origins(cors_origins: list[str] | None = None) -> list[str]:
    """Allowed CORS origins: argument → env ``CORS_ORIGINS`` (comma-separated) → localhost:3000.

    ``*`` is rejected because the API relies on credentialed (cookie) requests.
    """
    if cors_origins is None:
        raw = os.environ.get("CORS_ORIGINS", "")
        cors_origins = [o.strip() for o in raw.split(",") if o.strip()]
    origins = [o.strip() for o in cors_origins if o.strip()] or list(DEFAULT_CORS_ORIGINS)
    if "*" in origins:
        raise ValueError(
            "CORS origin '*' is not allowed together with credentials; list explicit origins"
        )
    return origins


def create_app(
    database_url: str | None = None,
    cookie_secure: bool = False,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Build the app; ``database_url`` follows the same resolution rule as the CLI commands.

    ``cookie_secure`` sets the ``Secure`` flag of the session cookie (off for local development).
    ``cors_origins`` overrides the ``CORS_ORIGINS`` environment variable.
    """
    origins = resolve_cors_origins(cors_origins)
    engine = make_engine(resolve_database_url(database_url))
    create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False, class_=Session)

    app = FastAPI(title="CineMate")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.matrix_store = MatrixStore(session_factory)
    app.state.cookie_secure = cookie_secure
    app.include_router(router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
