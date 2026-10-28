"""Engine creation and schema helpers."""

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool

from cinemate.db.models import Base


def _sqlite_lower(value):
    return value.lower() if isinstance(value, str) else value


def _unicode_lower(dbapi_connection, _record) -> None:
    # SQLite's built-in lower() only folds ASCII; search needs Cyrillic as well
    dbapi_connection.create_function("lower", 1, _sqlite_lower, deterministic=True)


def make_engine(url: str) -> Engine:
    """Create an engine for the given database URL (e.g. ``sqlite:///:memory:``)."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database in (None, "", ":memory:"):
        # One shared connection, usable from the threads a web server handles requests in.
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        engine = create_engine(url)
    if parsed.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _unicode_lower)
    return engine


def create_all(engine: Engine) -> None:
    """Create all tables that do not exist yet."""
    Base.metadata.create_all(engine)
