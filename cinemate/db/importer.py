"""Idempotent import of MovieLens into the database."""

import contextlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.binarize import Binarizer
from cinemate.db.catalog import CatalogConflict, find_movie, link, merge_movies
from cinemate.db.models import Movie, MovieExternalId, Rating, User
from cinemate.db.popularity import update_popularity
from cinemate.movielens import parse_links, parse_movies, parse_ratings


@dataclass(frozen=True)
class ImportStats:
    movies_added: int
    users_added: int
    ratings_added: int
    ratings_skipped: int
    popularity_updated: int
    movies_merged: int = 0


def import_movielens(session: Session, data_dir: Path, binarizer: Binarizer) -> ImportStats:
    """Import ``movies.csv``, ``links.csv`` and ``ratings.csv`` from ``data_dir``.

    Movies and users are matched by their MovieLens id, so a repeated import updates movies
    in place and adds nothing new. Ratings the binarizer discards are counted as skipped;
    the alternative title fills ``original_title`` only while it is empty, so a TMDB value is
    kept; a (user, movie) pair that already exists is left untouched and not counted at all.
    Finally ``Movie.popularity_score`` is recomputed as the number of ``+1`` ratings.
    """
    data_dir = Path(data_dir)
    links = {link_.movielens_id: link_ for link_ in parse_links(data_dir / "links.csv")}
    movies: dict[int, Movie] = {}
    movies_added = movies_merged = 0
    for parsed in parse_movies(data_dir / "movies.csv"):
        parsed_link = links.get(parsed.movielens_id)
        tmdb = ("movie", parsed_link.tmdb_id) if parsed_link and parsed_link.tmdb_id else None
        movie = find_movie(session, tmdb=tmdb, ids={"movielens": str(parsed.movielens_id)})
        if movie is None:
            movie = Movie(external_movielens_id=parsed.movielens_id, title=parsed.title)
            session.add(movie)
            movies_added += 1
        existing_link = session.get(MovieExternalId, ("movielens", str(parsed.movielens_id)))
        if existing_link is not None and existing_link.movie_id != movie.id:
            # the TMDB pair and the MovieLens id belong to different movies: the pair owner stays
            dropped = session.get(Movie, existing_link.movie_id)
            keep_id, drop_id = movie.id, existing_link.movie_id
            merge_movies(session, keep_id, drop_id)
            movies_merged += 1
            movie = session.get(Movie, keep_id)
            for key, value in movies.items():
                if value is dropped:
                    movies[key] = movie
        movies[parsed.movielens_id] = movie
        # a movie matched through another source (or another MovieLens duplicate) only gets
        # linked: its own data stays as it is
        if movie.external_movielens_id == parsed.movielens_id:
            movie.title = parsed.title
            if parsed.alt_title and not movie.original_title:
                movie.original_title = parsed.alt_title
            movie.year = parsed.year
            movie.genres = list(parsed.genres)
        if tmdb is not None and movie.tmdb_id is None:
            movie.tmdb_type, movie.tmdb_id = tmdb
        if parsed_link is not None and parsed_link.imdb_id and movie.imdb_id is None:
            movie.imdb_id = parsed_link.imdb_id
        link(session, movie, "movielens", parsed.movielens_id)
        if parsed_link is not None and parsed_link.imdb_id:
            # an IMDb id that belongs to another movie is left unlinked
            with contextlib.suppress(CatalogConflict):
                link(session, movie, "imdb", parsed_link.imdb_id)

    users = {
        u.external_movielens_id: u
        for u in session.scalars(select(User).where(User.external_movielens_id.is_not(None)))
    }
    existing = {(u, m) for u, m in session.execute(select(Rating.user_id, Rating.movie_id))}
    session.flush()

    users_added = ratings_added = ratings_skipped = 0
    for rating in parse_ratings(data_dir / "ratings.csv"):
        value = binarizer.binarize(rating.score, rating.user_id)
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
    popularity_updated = update_popularity(session)
    session.commit()
    return ImportStats(
        movies_added,
        users_added,
        ratings_added,
        ratings_skipped,
        popularity_updated,
        movies_merged,
    )
