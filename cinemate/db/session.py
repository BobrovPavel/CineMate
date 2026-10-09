"""Engine creation and schema helpers."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool

from cinemate.db.models import Base


def make_engine(url: str) -> Engine:
    """Create an engine for the given database URL (e.g. ``sqlite:///:memory:``)."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database in (None, "", ":memory:"):
        # One shared connection, usable from the threads a web server handles requests in.
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url)


def create_all(engine: Engine) -> None:
    """Create all tables that do not exist yet."""
    Base.metadata.create_all(engine)
