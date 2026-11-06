"""Ratings of a movie on several platforms for the movie card: TMDB, IMDb, CineMate, Kinopoisk."""

import os
from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from cinemate.db.models import ExternalRating, Movie, MovieExternalId, Rating, User

CINEMATE_MIN_RATINGS = 10
SHOW_KINOPOISK_ENV = "SHOW_KINOPOISK_RATING"
KINOPOISK_MODES = {"ru", "all", "off"}
_LEGACY_KINOPOISK_MODES = {"1": "all", "0": "off"}


@dataclass(frozen=True)
class RatingOut:
    """``scale`` is ``"10"`` (value out of 10) or ``"%"`` (share of likes, 0-100)."""

    source: str
    label: str
    value: float
    scale: str
    votes: int | None
    url: str | None


def kinopoisk_mode() -> str:
    """``SHOW_KINOPOISK_RATING``: ``ru`` (default), ``all`` or ``off``; legacy ``1``/``0``
    mean ``all``/``off``; an unknown value falls back to ``ru``."""
    raw = os.environ.get(SHOW_KINOPOISK_ENV, "").strip().lower()
    raw = _LEGACY_KINOPOISK_MODES.get(raw, raw)
    return raw if raw in KINOPOISK_MODES else "ru"


def show_kinopoisk_rating(language: str) -> bool:
    """Whether the Kinopoisk rating is shown for a request in ``language``."""
    mode = kinopoisk_mode()
    return mode == "all" or (mode == "ru" and language == "ru")


def cinemate_rating(session: Session, movie_id: int, pool: str) -> tuple[float, int] | None:
    """Share of likes (percent) and the number of ratings among the users of ``pool``;
    ``None`` below ``CINEMATE_MIN_RATINGS`` ratings."""
    likes, total = session.execute(
        select(func.coalesce(func.sum(case((Rating.value == 1, 1), else_=0)), 0), func.count())
        .select_from(Rating)
        .join(User, User.id == Rating.user_id)
        .where(Rating.movie_id == movie_id, User.pool == pool)
    ).one()
    if total < CINEMATE_MIN_RATINGS:
        return None
    return round(100 * likes / total, 1), total


def movie_ratings(session: Session, movie: Movie, pool: str, language: str) -> list[RatingOut]:
    """Ratings that exist for ``movie``, in the order Kinopoisk (if shown), IMDb,
    TMDB, CineMate."""
    cards: dict[str, RatingOut] = {}
    if movie.tmdb_vote_count and movie.tmdb_vote_average is not None and movie.tmdb_type:
        cards["tmdb"] = RatingOut(
            "tmdb",
            "TMDB",
            movie.tmdb_vote_average,
            "10",
            movie.tmdb_vote_count,
            f"https://www.themoviedb.org/{movie.tmdb_type}/{movie.tmdb_id}",
        )
    stored = {
        r.source: r
        for r in session.scalars(select(ExternalRating).where(ExternalRating.movie_id == movie.id))
    }
    imdb = stored.get("imdb")
    if imdb is not None:
        imdb_id = movie.imdb_id or session.scalar(
            select(MovieExternalId.external_id)
            .where(MovieExternalId.movie_id == movie.id, MovieExternalId.source == "imdb")
            .order_by(MovieExternalId.external_id)
        )
        url = f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else None
        cards["imdb"] = RatingOut("imdb", "IMDb", imdb.value, "10", imdb.votes, url)
    own = cinemate_rating(session, movie.id, pool)
    if own is not None:
        cards["cinemate"] = RatingOut("cinemate", "CineMate", own[0], "%", own[1], None)
    kinopoisk = stored.get("kinopoisk")
    if kinopoisk is not None and show_kinopoisk_rating(language):
        kp_id = session.scalar(
            select(MovieExternalId.external_id)
            .where(MovieExternalId.movie_id == movie.id, MovieExternalId.source == "kinopoisk")
            .order_by(MovieExternalId.external_id)
        )
        url = f"https://www.kinopoisk.ru/film/{kp_id}/" if kp_id else None
        label = "Кинопоиск" if language == "ru" else "Kinopoisk"
        cards["kinopoisk"] = RatingOut(
            "kinopoisk", label, kinopoisk.value, "10", kinopoisk.votes or None, url
        )
    order = ["kinopoisk", "imdb", "tmdb", "cinemate"]
    return [cards[k] for k in order if k in cards]
