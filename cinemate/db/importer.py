"""Idempotent import of MovieLens into the database."""

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.binarize import Binarizer
from cinemate.db.catalog import CatalogConflict, find_movie, link
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


def import_movielens(session: Session, data_dir: Path, binarizer: Binarizer) -> ImportStats:
    """Import ``movies.csv``, ``links.csv`` and ``ratings.csv`` from ``data_dir``.

    Movies are matched by their MovieLens id (``movie_external_ids``), then by the TMDB pair
    from ``links.csv`` (such a movie only gets the MovieLens id linked); users by their id. A
    repeated import updates movies in place and adds nothing new. Ratings the binarizer
    discards are counted as skipped; the alternative title fills ``original_title`` only while
    it is empty, so a TMDB value is kept; a (user, movie) pair that already exists is left
    untouched and not counted at all.
    Finally ``Movie.popularity_score`` is recomputed as the number of ``+1`` ratings.
    """
    data_dir = Path(data_dir)
    links = {link.movielens_id: link for link in parse_links(data_dir / "links.csv")}
    movies = {
        int(source_id): m
        for source_id, m in session.execute(
            select(MovieExternalId.external_id, Movie)
            .join(Movie, Movie.id == MovieExternalId.movie_id)
            .where(MovieExternalId.source == "movielens")
        )
    }
    movies_added = 0
    for parsed in parse_movies(data_dir / "movies.csv"):
        link_row = links.get(parsed.movielens_id)
        tmdb = ("movie", link_row.tmdb_id) if link_row and link_row.tmdb_id is not None else None
        movie = movies.get(parsed.movielens_id)
        if movie is None and tmdb is not None:
            # Same film already in the catalog (e.g. another MovieLens id): just link to it.
            movie = find_movie(session, tmdb=tmdb)
            if movie is not None:
                link(session, movie, "movielens", parsed.movielens_id)
                movies[parsed.movielens_id] = movie
                continue
        if movie is None:
            movie = Movie(title=parsed.title)
            session.add(movie)
            session.flush()
            link(session, movie, "movielens", parsed.movielens_id)
            movies[parsed.movielens_id] = movie
            movies_added += 1
        movie.title = parsed.title
        if parsed.alt_title and not movie.original_title:
            movie.original_title = parsed.alt_title
        movie.year = parsed.year
        movie.genres = list(parsed.genres)
        if link_row is not None:
            if link_row.imdb_id:
                with suppress(CatalogConflict):
                    link(session, movie, "imdb", link_row.imdb_id)
            if tmdb is not None and movie.tmdb_id is None:
                movie.tmdb_type, movie.tmdb_id = tmdb

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
        movies_added, users_added, ratings_added, ratings_skipped, popularity_updated
    )
