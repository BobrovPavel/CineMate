"""Initial schema: movies, users, ratings, seen_marks, events.

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "movies",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("imdb_id", sa.String(length=16), nullable=True),
        sa.Column("external_movielens_id", sa.Integer(), nullable=True),
        sa.Column("external_kinopoisk_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("original_title", sa.String(length=512), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("poster_path", sa.String(length=512), nullable=True),
        sa.Column("genres", sa.JSON(), nullable=False),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("popularity_score", sa.Float(), nullable=True),
        sa.UniqueConstraint("external_movielens_id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("session_token", sa.String(length=128), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("external_movielens_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("session_token"),
        sa.UniqueConstraint("external_movielens_id"),
    )
    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "movie_id", name="uq_ratings_user_movie"),
        sa.CheckConstraint("value IN (1, -1)", name="ck_ratings_value"),
    )
    op.create_table(
        "seen_marks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("user_id", "movie_id", name="uq_seen_marks_user_movie"),
        sa.CheckConstraint(
            "type IN ('not_seen', 'watched', 'not_interested')", name="ck_seen_marks_type"
        ),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), nullable=True),
        sa.Column("strategy", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('impression', 'like', 'dislike', 'watched', 'not_interested')",
            name="ck_events_type",
        ),
        sa.CheckConstraint(
            "strategy IS NULL OR strategy IN ('collaborative', 'fallback')",
            name="ck_events_strategy",
        ),
    )
    op.create_index("ix_events_session_id", "events", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_events_session_id", table_name="events")
    op.drop_table("events")
    op.drop_table("seen_marks")
    op.drop_table("ratings")
    op.drop_table("users")
    op.drop_table("movies")
