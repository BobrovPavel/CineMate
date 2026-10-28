"""Trigram indexes on movie titles for search in our own catalog (PostgreSQL only).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# the expressions are exactly the ones cinemate.services.search.search_local queries
_INDEXES = {
    "ix_movies_title_trgm": "title",
    "ix_movies_original_title_trgm": "original_title",
    "ix_movies_title_ru_trgm": "title_ru",
}


# must equal cinemate.services.search._normalized_column
_PUNCTUATION = "-:.·'’,!?\"()&/;"


def _normalized(column: str) -> str:
    expr = f"replace(lower({column}), 'ё', 'е')"
    for char in _PUNCTUATION:
        expr = f"replace({expr}, '{char.replace(chr(39), chr(39) * 2)}', ' ')"
    for _ in range(2):
        expr = f"replace({expr}, '  ', ' ')"
    return f"trim({expr})"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, column in _INDEXES.items():
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON movies "
            f"USING gin ({_normalized(column)} gin_trgm_ops)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
