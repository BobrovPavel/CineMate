"""Parsers for MovieLens CSV files (movies, ratings, links)."""

import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_YEAR_RE = re.compile(r"^(?P<title>.*?)\s*\((?P<year>\d{4})\)\s*$")
_NO_GENRES = "(no genres listed)"


@dataclass(frozen=True)
class Movie:
    movielens_id: int
    title: str
    year: int | None
    genres: tuple[str, ...]


@dataclass(frozen=True)
class Rating:
    user_id: int
    movie_id: int
    score: float


@dataclass(frozen=True)
class Link:
    movielens_id: int
    imdb_id: str | None
    tmdb_id: int | None


def _rows(path: Path | str) -> Iterator[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def _split_title(raw: str) -> tuple[str, int | None]:
    """Split ``Toy Story (1995)`` into ``("Toy Story", 1995)``; year is ``None`` if absent."""
    match = _YEAR_RE.match(raw.strip())
    if match is None:
        return raw.strip(), None
    return match["title"], int(match["year"])


def parse_movies(path: Path | str) -> Iterator[Movie]:
    """Yield movies from ``movies.csv``."""
    for row in _rows(path):
        title, year = _split_title(row["title"])
        raw_genres = row["genres"].strip()
        genres = () if raw_genres in ("", _NO_GENRES) else tuple(raw_genres.split("|"))
        yield Movie(int(row["movieId"]), title, year, genres)


def parse_ratings(path: Path | str) -> Iterator[Rating]:
    """Yield ratings from ``ratings.csv``."""
    for row in _rows(path):
        yield Rating(int(row["userId"]), int(row["movieId"]), float(row["rating"]))


def parse_links(path: Path | str) -> Iterator[Link]:
    """Yield links from ``links.csv``; ``imdb_id`` is ``tt`` + 7 digits, empty ids are ``None``."""
    for row in _rows(path):
        imdb = row["imdbId"].strip()
        tmdb = row["tmdbId"].strip()
        yield Link(
            int(row["movieId"]),
            f"tt{int(imdb):07d}" if imdb else None,
            int(tmdb) if tmdb else None,
        )
