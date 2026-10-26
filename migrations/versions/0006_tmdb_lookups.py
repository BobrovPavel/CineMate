"""TMDB lookup cache: tmdb_lookups.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tmdb_lookups",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("query_key", sa.String(length=256), nullable=False),
        sa.Column("tmdb_type", sa.String(length=8), nullable=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("kind", "query_key"),
    )


def downgrade() -> None:
    op.drop_table("tmdb_lookups")
