"""Idempotent import of an external ratings CSV (1-10 scale) into the database."""

import re
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.binarize import Binarizer
from cinemate.db.catalog import find_movie, link
from cinemate.db.models import Movie, MovieExternalId, Rating, User
from cinemate.db.popularity import update_popularity
from cinemate.ratings_csv import CsvRow, read_rows

_NON_WORD = re.compile(r"[\W_]+")


@dataclass(frozen=True)
class RatingsImportStats:
    movies_merged: int
    movies_added: int
    movies_ambiguous: int
    movies_skipped_no_title: int
    users_added: int
    ratings_added: int
    ratings_skipped: int
    popularity_updated: int


def normalize_title(title: str) -> str:
    """Casefold, drop punctuation and collapse whitespace."""
    return _NON_WORD.sub(" ", title.casefold()).strip()


def import_ratings_csv(
    session: Session,
    path: Path | str,
    binarizer: Binarizer,
    types: Collection[str] | None = None,
) -> RatingsImportStats:
    """Import movies, users and ``+1``/``-1`` ratings from the ratings CSV at ``path``.

    A movie is matched by its ``ratings_csv`` external id; otherwise it is merged into the single
    existing movie with the same normalised title and year (``title_original`` against ``title``
    or ``original_title``), else created. Ambiguous matches create a separate movie. Users are
    created (``is_synthetic``, no names) when they get at least one rating. Ratings the binarizer
    discards, ratings of skipped movies and existing (user, movie) pairs are not (re)added.
    With ``types`` only movies of those types (case-insensitive) are imported.
    """
    wanted = {t.strip().lower() for t in types} if types is not None else None
    movie_rows: dict[int, CsvRow] = {}
    scores: dict[tuple[int, int], int] = {}
    for row in read_rows(path):
        if wanted is not None and (row.type is None or row.type.lower() not in wanted):
            continue
        first = movie_rows.get(row.movie_id)
        movie_rows[row.movie_id] = row if first is None else _fill_gaps(first, row)
        scores[(row.user_id, row.movie_id)] = row.user_rating

    movies: dict[int, Movie] = {}
    csv_linked: set[int] = set()
    for source_id, movie_id in session.execute(
        select(MovieExternalId.external_id, MovieExternalId.movie_id).where(
            MovieExternalId.source == "ratings_csv"
        )
    ):
        csv_linked.add(movie_id)
        found_movie = session.get(Movie, movie_id)
        if found_movie is not None:
            movies[int(source_id)] = found_movie
    index: dict[tuple[str, int], set[int]] = defaultdict(set)
    by_id: dict[int, Movie] = {}
    for m in session.scalars(select(Movie).where(Movie.year.is_not(None))):
        by_id[m.id] = m
        for name in (m.title, m.original_title):
            if name:
                index[(normalize_title(name), m.year)].add(m.id)

    merged = added = ambiguous = no_title = 0
    for ext_id, row in movie_rows.items():
        movie = movies.get(ext_id) or find_movie(session, ids={"ratings_csv": str(ext_id)})
        if movie is not None:
            movies[ext_id] = movie
            _fill_empty(movie, row)
            continue
        candidates = _candidates(index, row)
        if len(candidates) == 1:
            found = by_id[next(iter(candidates))]
            if found.id not in csv_linked:
                found.external_ratings_id = ext_id
                link(session, found, "ratings_csv", ext_id)
                csv_linked.add(found.id)
                movies[ext_id] = found
                merged += 1
                continue
        if candidates:
            ambiguous += 1
        title = row.title_ru or row.title_original
        if title is None:
            no_title += 1
            continue
        movie = Movie(
            external_ratings_id=ext_id,
            title=title,
            original_title=row.title_original,
            year=row.year,
            genres=list(row.genres),
        )
        session.add(movie)
        link(session, movie, "ratings_csv", ext_id)
        csv_linked.add(movie.id)
        movies[ext_id] = movie
        added += 1

    users = {
        u.external_ratings_id: u
        for u in session.scalars(select(User).where(User.external_ratings_id.is_not(None)))
    }
    session.flush()
    existing = {(u, m) for u, m in session.execute(select(Rating.user_id, Rating.movie_id))}

    users_added = ratings_added = ratings_skipped = 0
    for (ext_user, ext_movie), score in scores.items():
        movie = movies.get(ext_movie)
        value = binarizer.binarize(float(score), ext_user)
        if movie is None or value is None:
            ratings_skipped += 1
            continue
        user = users.get(ext_user)
        if user is None:
            user = User(external_ratings_id=ext_user, is_synthetic=True)
            session.add(user)
            session.flush()
            users[ext_user] = user
            users_added += 1
        if (user.id, movie.id) in existing:
            continue
        existing.add((user.id, movie.id))
        session.add(Rating(user_id=user.id, movie_id=movie.id, value=value))
        ratings_added += 1

    session.flush()
    popularity_updated = update_popularity(session)
    session.commit()
    return RatingsImportStats(
        merged,
        added,
        ambiguous,
        no_title,
        users_added,
        ratings_added,
        ratings_skipped,
        popularity_updated,
    )


def _candidates(index: dict[tuple[str, int], set[int]], row: CsvRow) -> set[int]:
    if not row.title_original or row.year is None:
        return set()
    return index.get((normalize_title(row.title_original), row.year), set())


def _fill_gaps(first: CsvRow, other: CsvRow) -> CsvRow:
    """``first`` with its empty movie fields taken from ``other``."""
    return CsvRow(
        user_id=first.user_id,
        movie_id=first.movie_id,
        user_rating=first.user_rating,
        title_ru=first.title_ru or other.title_ru,
        title_original=first.title_original or other.title_original,
        type=first.type or other.type,
        year=first.year if first.year is not None else other.year,
        genres=first.genres or other.genres,
    )


def _fill_empty(movie: Movie, row: CsvRow) -> None:
    if movie.original_title is None and row.title_original:
        movie.original_title = row.title_original
    if movie.year is None and row.year is not None:
        movie.year = row.year
    if not movie.genres and row.genres:
        movie.genres = list(row.genres)
