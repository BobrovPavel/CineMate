"""Catalog keys: movies.tmdb_type, unique TMDB pair and movie_external_ids.

Existing external ids are copied into ``movie_external_ids``; movies sharing a TMDB id are merged
into the one with the smallest id before the unique constraint is created.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_COLUMNS = (
    ("movielens", "external_movielens_id"),
    ("imdb", "imdb_id"),
    ("kinopoisk", "external_kinopoisk_id"),
    ("ratings_csv", "external_ratings_id"),
)


def upgrade() -> None:
    with op.batch_alter_table("movies") as batch:
        batch.add_column(sa.Column("tmdb_type", sa.String(length=8), nullable=True))
    op.create_table(
        "movie_external_ids",
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=32), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"]),
        sa.PrimaryKeyConstraint("source", "external_id"),
    )
    op.create_index("ix_movie_external_ids_movie_id", "movie_external_ids", ["movie_id"])

    conn = op.get_bind()
    movies = sa.table(
        "movies",
        sa.column("id", sa.Integer),
        sa.column("tmdb_type", sa.String),
        sa.column("tmdb_id", sa.Integer),
        *(sa.column(col) for _, col in _OLD_COLUMNS),
    )
    ext = sa.table(
        "movie_external_ids",
        sa.column("source", sa.String),
        sa.column("external_id", sa.String),
        sa.column("movie_id", sa.Integer),
    )
    conn.execute(sa.update(movies).where(movies.c.tmdb_id.is_not(None)).values(tmdb_type="movie"))

    seen: set[tuple[str, str]] = set()
    rows = []
    for source, col in _OLD_COLUMNS:
        query = sa.select(movies.c.id, movies.c[col]).where(movies.c[col].is_not(None))
        for movie_id, value in conn.execute(query.order_by(movies.c.id)):
            key = (source, str(value))
            if key not in seen:  # imdb/kinopoisk ids are not unique in the old columns
                seen.add(key)
                rows.append({"source": source, "external_id": str(value), "movie_id": movie_id})
    if rows:
        conn.execute(sa.insert(ext), rows)

    _merge_duplicate_tmdb_pairs(conn, movies)

    with op.batch_alter_table("movies") as batch:
        batch.create_check_constraint("ck_movies_tmdb_type", "tmdb_type IN ('movie', 'tv')")
        batch.create_unique_constraint("uq_movies_tmdb", ["tmdb_type", "tmdb_id"])


def _merge_duplicate_tmdb_pairs(conn, movies) -> None:
    ratings = sa.table(
        "ratings",
        sa.column("id", sa.Integer),
        sa.column("user_id", sa.Integer),
        sa.column("movie_id", sa.Integer),
        sa.column("value", sa.Integer),
        sa.column("created_at", sa.DateTime),
    )
    marks = sa.table(
        "seen_marks",
        sa.column("id", sa.Integer),
        sa.column("user_id", sa.Integer),
        sa.column("movie_id", sa.Integer),
        sa.column("type", sa.String),
    )
    events = sa.table("events", sa.column("movie_id", sa.Integer))
    ext = sa.table("movie_external_ids", sa.column("movie_id", sa.Integer))

    groups: dict[tuple[str, int], list[int]] = {}
    query = (
        sa.select(movies.c.id, movies.c.tmdb_type, movies.c.tmdb_id)
        .where(movies.c.tmdb_id.is_not(None))
        .order_by(movies.c.id)
    )
    for movie_id, tmdb_type, tmdb_id in conn.execute(query):
        groups.setdefault((tmdb_type, tmdb_id), []).append(movie_id)

    for ids in groups.values():
        keep, drops = ids[0], ids[1:]
        for drop in drops:
            kept = {
                r.user_id: r
                for r in conn.execute(sa.select(ratings).where(ratings.c.movie_id == keep))
            }
            for r in conn.execute(sa.select(ratings).where(ratings.c.movie_id == drop)).all():
                mine = kept.get(r.user_id)
                if mine is None:
                    conn.execute(
                        sa.update(ratings).where(ratings.c.id == r.id).values(movie_id=keep)
                    )
                    continue
                if r.created_at > mine.created_at:
                    conn.execute(
                        sa.update(ratings)
                        .where(ratings.c.id == mine.id)
                        .values(value=r.value, created_at=r.created_at)
                    )
                conn.execute(sa.delete(ratings).where(ratings.c.id == r.id))

            kept_marks = {
                m.user_id: m for m in conn.execute(sa.select(marks).where(marks.c.movie_id == keep))
            }
            for m in conn.execute(sa.select(marks).where(marks.c.movie_id == drop)).all():
                mine = kept_marks.get(m.user_id)
                if mine is None:
                    conn.execute(sa.update(marks).where(marks.c.id == m.id).values(movie_id=keep))
                    continue
                if m.id > mine.id:  # seen marks have no timestamp: the later row is newer
                    conn.execute(sa.update(marks).where(marks.c.id == mine.id).values(type=m.type))
                conn.execute(sa.delete(marks).where(marks.c.id == m.id))

            conn.execute(sa.update(events).where(events.c.movie_id == drop).values(movie_id=keep))
            conn.execute(sa.update(ext).where(ext.c.movie_id == drop).values(movie_id=keep))
            conn.execute(sa.delete(movies).where(movies.c.id == drop))


def downgrade() -> None:
    with op.batch_alter_table("movies") as batch:
        batch.drop_constraint("uq_movies_tmdb", type_="unique")
        batch.drop_constraint("ck_movies_tmdb_type", type_="check")
        batch.drop_column("tmdb_type")
    op.drop_index("ix_movie_external_ids_movie_id", table_name="movie_external_ids")
    op.drop_table("movie_external_ids")
