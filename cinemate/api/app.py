"""Application factory: engine, schema and :class:`MatrixStore` are created once at startup."""

import os
from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from cinemate.api.routes import router
from cinemate.cli import resolve_database_url
from cinemate.config import RecommenderSettings
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.migrations import ensure_schema
from cinemate.db.session import make_engine
from cinemate.services.search import SearchCache
from cinemate.tmdb import TmdbClient

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


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def resolve_cookie_secure(flag: bool, environ: Mapping[str, str] | None = None) -> bool:
    """Secure flag of the session cookie: ``flag`` → env ``COOKIE_SECURE`` → off.

    Accepts ``1/true/yes/on`` and ``0/false/no/off`` (case-insensitive); empty means off.
    Raises ``ValueError`` naming the variable for anything else.
    """
    if flag:
        return True
    env = os.environ if environ is None else environ
    raw = env.get("COOKIE_SECURE", "").strip().lower()
    if not raw or raw in _FALSE_VALUES:
        return False
    if raw in _TRUE_VALUES:
        return True
    raise ValueError(f"COOKIE_SECURE: invalid value {raw!r}; use 1/true/yes/on or 0/false/no/off")


def create_app(
    database_url: str | None = None,
    cookie_secure: bool = False,
    cors_origins: list[str] | None = None,
    recommender_settings: RecommenderSettings | None = None,
    tmdb_client: TmdbClient | None = None,
) -> FastAPI:
    """Build the app; ``database_url`` follows the same resolution rule as the CLI commands.

    ``cookie_secure`` sets the ``Secure`` flag of the session cookie (off for local development).
    ``cors_origins`` overrides the ``CORS_ORIGINS`` environment variable.
    ``tmdb_client`` overrides the client built from env ``TMDB_API_KEY`` (tests pass a fake).
    ``recommender_settings`` overrides the ``REC_*`` environment variables; invalid ones raise
    ``ValueError`` at startup. A database that is not on the latest migration revision raises
    ``SchemaNotMigratedError`` (in-memory SQLite and empty SQLite files are set up automatically).
    """
    origins = resolve_cors_origins(cors_origins)
    settings = recommender_settings or RecommenderSettings.from_env()
    engine = make_engine(resolve_database_url(database_url))
    ensure_schema(engine)
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
    app.state.recommender_settings = settings
    app.state.cookie_secure = cookie_secure
    api_key = os.environ.get("TMDB_API_KEY", "").strip()
    # without a key the search endpoints answer 503
    app.state.tmdb_client = tmdb_client or (TmdbClient(api_key) if api_key else None)
    app.state.search_cache = SearchCache()
    app.include_router(router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
