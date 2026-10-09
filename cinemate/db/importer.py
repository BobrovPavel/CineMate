"""Idempotent import of MovieLens into the database."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from cinemate.binarize import Binarizer
from cinemate.db.models import Movie, Rating, User
from cinemate.movielens import parse_links, parse_movies, parse_ratings


@dataclass(frozen=True)
class ImportStats:
    movies_added: int
    users_added: int
    ratings_added: int
    ratings_skipped: int
    popularity_updated: int


def import_movielens(session: Session, data_dir: Path, binarizer: Binarizer) -> ImportStats:
    """Import ``movies.csv``, ``links.csv`` and ``ratings.csv`` from ``data_dir``.

    Movies and users are matched by their MovieLens id, so a repeated import updates movies
    in place and adds nothing new. Ratings the binarizer discards are counted as skipped;
    a (user, movie) pair that already exists is left untouched and not counted at all.
    Finally ``Movie.popularity_score`` is recomputed as the number of ``+1`` ratings.
    """
    data_dir = Path(data_dir)
    links = {link.movielens_id: link for link in parse_links(data_dir / "links.csv")}
    movies = {
        m.external_movielens_id: m
        for m in session.scalars(select(Movie).where(Movie.external_movielens_id.is_not(None)))
    }
    movies_added = 0
    for parsed in parse_movies(data_dir / "movies.csv"):
        link = links.get(parsed.movielens_id)
        movie = movies.get(parsed.movielens_id)
        if movie is None:
            movie = Movie(external_movielens_id=parsed.movielens_id)
            session.add(movie)
            movies[parsed.movielens_id] = movie
            movies_added += 1
        movie.title = parsed.title
        movie.year = parsed.year
        movie.genres = list(parsed.genres)
        if link is not None:
            movie.imdb_id = link.imdb_id
            movie.tmdb_id = link.tmdb_id

    users = {
        u.external_movielens_id: u
        for u in session.scalars(select(User).where(User.external_movielens_id.is_not(None)))
    }
    existing = {(u, m) for u, m in session.execute(select(Rating.user_id, Rating.movie_id))}
    session.flush()

    users_added = ratings_added = ratings_skipped = 0
    for rating in parse_ratings(data_dir / "ratings.csv"):
        value = binarizer.binarize(rating.score)
        if value is None:
            ratings_skipped += 1
            continue
        movie = movies.get(rating.movie_id)
        if movie is None:
            ratings_skipped += 1
            continue
        user = users.get(rating.user_id)
        if user is None:
            user = User(external_movielens_id=rating.user_id, is_synthetic=True)
            session.add(user)
            session.flush()
            users[rating.user_id] = user
            users_added += 1
        key = (user.id, movie.id)
        if key in existing:
            continue
        existing.add(key)
        session.add(Rating(user_id=user.id, movie_id=movie.id, value=value))
        ratings_added += 1

    session.flush()
    popularity_updated = _update_popularity(session)
    session.commit()
    return ImportStats(
        movies_added, users_added, ratings_added, ratings_skipped, popularity_updated
    )


def _update_popularity(session: Session, batch_size: int = 1000) -> int:
    """Set ``Movie.popularity_score`` to the like count; return how many values changed."""
    likes = dict(
        session.execute(
            select(Rating.movie_id, func.count()).where(Rating.value == 1).group_by(Rating.movie_id)
        ).all()
    )
    current = session.execute(select(Movie.id, Movie.popularity_score)).all()
    changes = [
        {"id": movie_id, "popularity_score": float(likes.get(movie_id, 0))}
        for movie_id, score in current
        if score != likes.get(movie_id, 0)
    ]
    for start in range(0, len(changes), batch_size):
        session.execute(update(Movie), changes[start : start + batch_size])
    return len(changes)
