"""Catalog keys: movies.tmdb_type, movie_external_ids, merge of TMDB duplicates.

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

# lightweight table definitions: the migration must not depend on the current models
movies = sa.table(
    "movies",
    sa.column("id", sa.Integer),
    sa.column("tmdb_type", sa.String),
    sa.column("tmdb_id", sa.Integer),
    sa.column("imdb_id", sa.String),
    sa.column("external_movielens_id", sa.Integer),
    sa.column("external_kinopoisk_id", sa.Integer),
    sa.column("external_ratings_id", sa.Integer),
    sa.column("original_title", sa.String),
    sa.column("title_ru", sa.String),
    sa.column("year", sa.Integer),
    sa.column("overview", sa.Text),
    sa.column("poster_path", sa.String),
    sa.column("genres", sa.JSON),
    sa.column("runtime", sa.Integer),
    sa.column("popularity_score", sa.Float),
)
external_ids = sa.table(
    "movie_external_ids",
    sa.column("source", sa.String),
    sa.column("external_id", sa.String),
    sa.column("movie_id", sa.Integer),
)
ratings = sa.table(
    "ratings",
    sa.column("id", sa.Integer),
    sa.column("user_id", sa.Integer),
    sa.column("movie_id", sa.Integer),
    sa.column("value", sa.Integer),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
seen_marks = sa.table(
    "seen_marks",
    sa.column("id", sa.Integer),
    sa.column("user_id", sa.Integer),
    sa.column("movie_id", sa.Integer),
    sa.column("type", sa.String),
)
events = sa.table("events", sa.column("movie_id", sa.Integer))

LEGACY_IDS = (
    ("movielens", "external_movielens_id"),
    ("imdb", "imdb_id"),
    ("kinopoisk", "external_kinopoisk_id"),
    ("ratings_csv", "external_ratings_id"),
)
FILL_FIELDS = (
    "imdb_id",
    "original_title",
    "title_ru",
    "year",
    "overview",
    "poster_path",
    "runtime",
)


def upgrade() -> None:
    with op.batch_alter_table("movies") as batch:
        batch.add_column(sa.Column("tmdb_type", sa.String(length=8), nullable=True))
    op.create_table(
        "movie_external_ids",
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=32), nullable=False),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), nullable=False),
        sa.PrimaryKeyConstraint("source", "external_id"),
    )
    op.create_index("ix_movie_external_ids_movie_id", "movie_external_ids", ["movie_id"])

    conn = op.get_bind()
    conn.execute(sa.update(movies).where(movies.c.tmdb_id.is_not(None)).values(tmdb_type="movie"))
    seen: set[tuple[str, str]] = set()
    for source, column in LEGACY_IDS:
        values = []
        for movie_id, value in conn.execute(
            sa.select(movies.c.id, movies.c[column])
            .where(movies.c[column].is_not(None))
            .order_by(movies.c.id)
        ):
            # two rows may share an id (MovieLens duplicates share the IMDb id): lowest id wins
            if (source, str(value)) not in seen:
                seen.add((source, str(value)))
                values.append({"source": source, "external_id": str(value), "movie_id": movie_id})
        if values:
            conn.execute(sa.insert(external_ids), values)

    groups: dict[int, list[int]] = {}
    for movie_id, tmdb_id in conn.execute(
        sa.select(movies.c.id, movies.c.tmdb_id)
        .where(movies.c.tmdb_id.is_not(None))
        .order_by(movies.c.id)
    ):
        groups.setdefault(tmdb_id, []).append(movie_id)
    for ids in groups.values():
        for drop_id in ids[1:]:
            _merge(conn, ids[0], drop_id)

    with op.batch_alter_table("movies") as batch:
        batch.create_check_constraint("ck_movies_tmdb_type", "tmdb_type IN ('movie', 'tv')")
        batch.create_unique_constraint("uq_movies_tmdb", ["tmdb_type", "tmdb_id"])


def _merge(conn, keep_id: int, drop_id: int) -> None:
    """Move ratings, seen marks, events and external ids of ``drop_id`` to ``keep_id``."""
    kept = {
        r.user_id: r for r in conn.execute(sa.select(ratings).where(ratings.c.movie_id == keep_id))
    }
    for rating in conn.execute(sa.select(ratings).where(ratings.c.movie_id == drop_id)).all():
        mine = kept.get(rating.user_id)
        if mine is None:
            conn.execute(
                sa.update(ratings).where(ratings.c.id == rating.id).values(movie_id=keep_id)
            )
            continue
        if rating.created_at is not None and (
            mine.created_at is None or rating.created_at > mine.created_at
        ):
            conn.execute(
                sa.update(ratings)
                .where(ratings.c.id == mine.id)
                .values(value=rating.value, created_at=rating.created_at)
            )
        conn.execute(sa.delete(ratings).where(ratings.c.id == rating.id))

    kept_marks = {
        m.user_id: m
        for m in conn.execute(sa.select(seen_marks).where(seen_marks.c.movie_id == keep_id))
    }
    for mark in conn.execute(sa.select(seen_marks).where(seen_marks.c.movie_id == drop_id)).all():
        mine = kept_marks.get(mark.user_id)
        if mine is None:
            conn.execute(
                sa.update(seen_marks).where(seen_marks.c.id == mark.id).values(movie_id=keep_id)
            )
            continue
        if mark.id > mine.id:  # seen marks have no timestamp: the higher id is the later one
            conn.execute(
                sa.update(seen_marks).where(seen_marks.c.id == mine.id).values(type=mark.type)
            )
        conn.execute(sa.delete(seen_marks).where(seen_marks.c.id == mark.id))

    conn.execute(sa.update(events).where(events.c.movie_id == drop_id).values(movie_id=keep_id))
    conn.execute(
        sa.update(external_ids).where(external_ids.c.movie_id == drop_id).values(movie_id=keep_id)
    )

    keep = conn.execute(sa.select(movies).where(movies.c.id == keep_id)).one()
    drop = conn.execute(sa.select(movies).where(movies.c.id == drop_id)).one()
    fill = {f: drop._mapping[f] for f in FILL_FIELDS if keep._mapping[f] is None}
    if not keep.genres and drop.genres:
        fill["genres"] = drop.genres
    likes = conn.execute(
        sa.select(sa.func.count())
        .select_from(ratings)
        .where(ratings.c.movie_id == keep_id, ratings.c.value == 1)
    ).scalar_one()
    conn.execute(sa.delete(movies).where(movies.c.id == drop_id))
    conn.execute(
        sa.update(movies)
        .where(movies.c.id == keep_id)
        .values(popularity_score=float(likes), **{k: v for k, v in fill.items() if v is not None})
    )


def downgrade() -> None:
    with op.batch_alter_table("movies") as batch:
        batch.drop_constraint("uq_movies_tmdb", type_="unique")
        batch.drop_constraint("ck_movies_tmdb_type", type_="check")
        batch.drop_column("tmdb_type")
    op.drop_index("ix_movie_external_ids_movie_id", table_name="movie_external_ids")
    op.drop_table("movie_external_ids")
