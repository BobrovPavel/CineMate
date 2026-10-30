"""Movie card data: people, credits, keywords, age rating, budget, revenue, tagline, seasons.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = "'cast', 'director', 'writer', 'producer', 'composer', 'creator'"


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), autoincrement=False, primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("profile_path", sa.String(length=512), nullable=True),
    )
    op.create_table(
        "movie_credits",
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), primary_key=True),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("people.id"), primary_key=True),
        sa.Column("role", sa.String(length=16), primary_key=True),
        sa.Column("character", sa.String(length=512), nullable=True),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"role IN ({ROLES})", name="ck_movie_credits_role"),
    )
    op.create_index("ix_movie_credits_person_id", "movie_credits", ["person_id"])
    op.create_table(
        "keywords",
        sa.Column("id", sa.Integer(), autoincrement=False, primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
    )
    op.create_table(
        "movie_keywords",
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), primary_key=True),
        sa.Column("keyword_id", sa.Integer(), sa.ForeignKey("keywords.id"), primary_key=True),
    )
    op.create_index("ix_movie_keywords_keyword_id", "movie_keywords", ["keyword_id"])
    with op.batch_alter_table("movies") as batch:
        batch.add_column(sa.Column("certification", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("certification_country", sa.String(length=2), nullable=True))
        batch.add_column(sa.Column("budget", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("revenue", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("tagline", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("number_of_seasons", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("number_of_episodes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("details_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("movies") as batch:
        for column in (
            "details_fetched_at",
            "number_of_episodes",
            "number_of_seasons",
            "tagline",
            "revenue",
            "budget",
            "certification_country",
            "certification",
        ):
            batch.drop_column(column)
    op.drop_index("ix_movie_keywords_keyword_id", table_name="movie_keywords")
    op.drop_table("movie_keywords")
    op.drop_table("keywords")
    op.drop_index("ix_movie_credits_person_id", table_name="movie_credits")
    op.drop_table("movie_credits")
    op.drop_table("people")
