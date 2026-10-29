"""Movie features: one genre dictionary, collections, companies, countries, language, TMDB vote.

The genre dictionary and the translation of the old ``movies.genres`` names come from
``cinemate.genres``. The ``movies.genres`` column stays; code uses ``movie_genres`` only.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-29
"""

from collections import Counter
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cinemate.genres import GENRES, legacy_genre_ids

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHUNK = 5000


def upgrade() -> None:
    genres = op.create_table(
        "genres",
        sa.Column("id", sa.Integer(), autoincrement=False, primary_key=True),
        sa.Column("name_en", sa.String(length=64), nullable=False),
        sa.Column("name_ru", sa.String(length=64), nullable=False),
    )
    op.create_table(
        "movie_genres",
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), primary_key=True),
        sa.Column("genre_id", sa.Integer(), sa.ForeignKey("genres.id"), primary_key=True),
    )
    op.create_index("ix_movie_genres_genre_id", "movie_genres", ["genre_id"])
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), autoincrement=False, primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), autoincrement=False, primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("logo_path", sa.String(length=512), nullable=True),
    )
    op.create_table(
        "movie_companies",
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), primary_key=True),
    )
    op.create_index("ix_movie_companies_company_id", "movie_companies", ["company_id"])

    with op.batch_alter_table("movies") as batch:
        batch.add_column(sa.Column("collection_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("countries", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("original_language", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("tmdb_vote_average", sa.Float(), nullable=True))
        batch.add_column(sa.Column("tmdb_vote_count", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_movies_collection_id", "collections", ["collection_id"], ["id"]
        )

    op.bulk_insert(
        genres, [{"id": g.id, "name_en": g.name_en, "name_ru": g.name_ru} for g in GENRES]
    )
    _translate_old_genres()


def _translate_old_genres() -> None:
    connection = op.get_bind()
    movies = sa.table("movies", sa.column("id", sa.Integer), sa.column("genres", sa.JSON))
    movie_genres = sa.table(
        "movie_genres", sa.column("movie_id", sa.Integer), sa.column("genre_id", sa.Integer)
    )
    dropped: Counter[str] = Counter()
    last_id = 0
    while True:
        rows = connection.execute(
            sa.select(movies.c.id, movies.c.genres)
            .where(movies.c.id > last_id)
            .order_by(movies.c.id)
            .limit(CHUNK)
        ).all()
        if not rows:
            break
        last_id = rows[-1][0]
        values = []
        for movie_id, names in rows:
            ids, lost = legacy_genre_ids(names or [])
            dropped.update(lost)
            values.extend({"movie_id": movie_id, "genre_id": g} for g in ids)
        if values:
            connection.execute(sa.insert(movie_genres), values)
    if dropped:
        print("0011: genre names without a match were dropped:", dict(dropped.most_common()))


def downgrade() -> None:
    with op.batch_alter_table("movies") as batch:
        batch.drop_constraint("fk_movies_collection_id", type_="foreignkey")
        batch.drop_column("tmdb_vote_count")
        batch.drop_column("tmdb_vote_average")
        batch.drop_column("original_language")
        batch.drop_column("countries")
        batch.drop_column("collection_id")
    op.drop_index("ix_movie_companies_company_id", table_name="movie_companies")
    op.drop_table("movie_companies")
    op.drop_table("companies")
    op.drop_table("collections")
    op.drop_index("ix_movie_genres_genre_id", table_name="movie_genres")
    op.drop_table("movie_genres")
    op.drop_table("genres")
