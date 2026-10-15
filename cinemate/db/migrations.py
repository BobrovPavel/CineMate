"""Alembic helpers: run migrations, stamp ``head`` and check the schema at startup."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from cinemate.db.session import create_all

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
MIGRATIONS_DIR_ENV = "CINEMATE_MIGRATIONS_DIR"
VERSION_TABLE = "alembic_version"


class SchemaNotMigratedError(RuntimeError):
    """The database schema is not on the latest migration revision."""


def migrations_dir() -> Path:
    """Migration scripts: env ``CINEMATE_MIGRATIONS_DIR``, else ``migrations/`` of the checkout.

    The default only works for a source checkout or an editable install; the Docker image sets
    the variable because the package is installed into site-packages there.
    """
    override = os.environ.get(MIGRATIONS_DIR_ENV)
    return Path(override) if override else DEFAULT_MIGRATIONS_DIR


def alembic_config(engine: Engine, script_location: Path | None = None) -> Config:
    """Alembic config bound to ``engine`` (``migrations/env.py`` reuses it, no URL needed)."""
    config = Config()
    config.set_main_option("script_location", str(script_location or migrations_dir()))
    config.attributes["engine"] = engine
    return config


def head_revision(script_location: Path | None = None) -> str:
    """The latest revision id of the migration scripts."""
    script = ScriptDirectory(str(script_location or migrations_dir()))
    head = script.get_current_head()
    if head is None:
        raise RuntimeError(
            f"no migration scripts found in {script.dir}; set {MIGRATIONS_DIR_ENV} if needed"
        )
    return head


def current_revision(engine: Engine) -> str | None:
    """Revision recorded in the database, ``None`` if it is not under migration control."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def has_tables(engine: Engine) -> bool:
    """Whether the database has any table besides the Alembic version table."""
    return any(name != VERSION_TABLE for name in inspect(engine).get_table_names())


def upgrade_head(engine: Engine, script_location: Path | None = None) -> None:
    """Apply all pending migrations."""
    command.upgrade(alembic_config(engine, script_location), "head")


def stamp_head(engine: Engine, script_location: Path | None = None) -> None:
    """Record ``head`` as the current revision without touching any table."""
    command.stamp(alembic_config(engine, script_location), "head")


def _is_memory_sqlite(engine: Engine) -> bool:
    url = engine.url
    return url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:")


def ensure_schema(engine: Engine) -> None:
    """Prepare the schema at application startup.

    In-memory SQLite (tests, development) gets ``create_all``. A SQLite file without tables is
    initialised by the migrations. Any other database must already be on the latest revision,
    otherwise ``SchemaNotMigratedError`` explains what to run.
    """
    if _is_memory_sqlite(engine):
        create_all(engine)
        return
    revision = current_revision(engine)
    if revision == head_revision():
        return
    sqlite = engine.dialect.name == "sqlite"
    if revision is None and not has_tables(engine):
        if sqlite:
            upgrade_head(engine)
            return
        raise SchemaNotMigratedError("the database schema is empty: run `cinemate migrate`")
    if revision is None:
        raise SchemaNotMigratedError(
            "the database was created without migrations: "
            "run `cinemate migrate --stamp-existing`, then `cinemate migrate`"
        )
    raise SchemaNotMigratedError("the database schema is outdated: run `cinemate migrate`")
