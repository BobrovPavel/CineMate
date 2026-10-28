"""catalog_sync: how far the TMDB /changes feed has been processed, per type.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_sync",
        sa.Column("tmdb_type", sa.String(length=8), primary_key=True),
        sa.Column("changes_synced_until", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("catalog_sync")
