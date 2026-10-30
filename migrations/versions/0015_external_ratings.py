"""Ratings of other platforms (IMDb, Kinopoisk): ``external_ratings``.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_ratings",
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), primary_key=True),
        sa.Column("source", sa.String(length=16), primary_key=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("votes", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('imdb', 'kinopoisk')", name="ck_external_ratings_source"),
    )


def downgrade() -> None:
    op.drop_table("external_ratings")
