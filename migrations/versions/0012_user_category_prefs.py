"""user_category_prefs: categories a user keeps in the feed despite their dislikes.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_category_prefs",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("kind", sa.String(length=16), primary_key=True),
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('show')", name="ck_user_category_prefs_mode"),
        sa.CheckConstraint(
            "kind IN ('collection', 'studio', 'genre', 'anime')",
            name="ck_user_category_prefs_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("user_category_prefs")
