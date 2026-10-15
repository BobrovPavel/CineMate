"""Alembic environment.

The database URL comes from ``resolve_database_url`` (env ``DATABASE_URL``, else the default
SQLite file) unless ``cinemate migrate`` passes an engine through ``config.attributes``.
"""

from alembic import context

from cinemate.cli import resolve_database_url
from cinemate.db.models import Base
from cinemate.db.session import make_engine

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=resolve_database_url(None),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = config.attributes.get("engine")
    own_engine = engine is None
    if own_engine:
        engine = make_engine(resolve_database_url(None))
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        if own_engine:
            engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
