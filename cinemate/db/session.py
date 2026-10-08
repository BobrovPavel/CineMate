"""Engine creation and schema helpers."""

from sqlalchemy import Engine, create_engine

from cinemate.db.models import Base


def make_engine(url: str) -> Engine:
    """Create an engine for the given database URL (e.g. ``sqlite:///:memory:``)."""
    return create_engine(url)


def create_all(engine: Engine) -> None:
    """Create all tables that do not exist yet."""
    Base.metadata.create_all(engine)
