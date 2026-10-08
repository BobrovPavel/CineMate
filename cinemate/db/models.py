"""SQLAlchemy 2.0 declarative models (see docs/VISION.md, data model)."""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all CineMate tables."""


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    imdb_id: Mapped[str | None] = mapped_column(String(16))
    external_movielens_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    external_kinopoisk_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    original_title: Mapped[str | None] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    overview: Mapped[str | None] = mapped_column(Text)
    poster_path: Mapped[str | None] = mapped_column(String(512))
    genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    runtime: Mapped[int | None] = mapped_column(Integer)
    popularity_score: Mapped[float | None] = mapped_column(Float)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_token: Mapped[str | None] = mapped_column(String(128), unique=True)
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    is_synthetic: Mapped[bool] = mapped_column(default=False)
    external_movielens_id: Mapped[int | None] = mapped_column(Integer, unique=True)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", name="uq_ratings_user_movie"),
        CheckConstraint("value IN (1, -1)", name="ck_ratings_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"))
    value: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SeenMark(Base):
    """Not a rating: never used for similarity, only for excluding movies from results."""

    __tablename__ = "seen_marks"
    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", name="uq_seen_marks_user_movie"),
        CheckConstraint(
            "type IN ('not_seen', 'watched', 'not_interested')", name="ck_seen_marks_type"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"))
    type: Mapped[str] = mapped_column(String(16))
