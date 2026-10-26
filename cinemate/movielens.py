"""Parsers for MovieLens CSV files (movies, ratings, links)."""

import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_YEAR_RE = re.compile(r"^(?P<title>.*?)\s*\((?P<year>\d{4})\)\s*$")
_TRAILING_PARENS_RE = re.compile(r"^(?P<head>.*?)\s*\((?P<inner>[^()]+)\)\s*$")
_ARTICLES = (
    "The", "A", "An", "Les", "La", "Le", "Las", "Los", "Lo", "Il", "El", "Das", "Der", "Die",
    "Den", "Det", "De", "Het", "Een", "L'", "Un", "Une",
)  # fmt: skip
_TRAILING_ARTICLE_RE = re.compile(
    r"^(?P<head>.*\S),\s+(?P<article>" + "|".join(re.escape(a) for a in _ARTICLES) + r")$",
    re.IGNORECASE,
)
_NO_GENRES = "(no genres listed)"


@dataclass(frozen=True)
class Movie:
    movielens_id: int
    title: str
    year: int | None
    genres: tuple[str, ...]
    alt_title: str | None = None


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


def _move_article(title: str) -> str:
    """Turn ``Blair Witch Project, The`` into ``The Blair Witch Project``."""
    match = _TRAILING_ARTICLE_RE.match(title)
    if match is None:
        return title
    article = match["article"]
    sep = "" if article.endswith("'") else " "
    return f"{article}{sep}{match['head']}"


def _split_title(raw: str) -> tuple[str, int | None, str | None]:
    """Split ``Blair Witch Project, The (1999)`` into title, year and alternative title.

    The trailing article moves to the front; parentheses right before the year hold the
    alternative title (the first one wins) and are removed from the title. Without a year
    the stripped input is returned as is.
    """
    match = _YEAR_RE.match(raw.strip())
    if match is None:
        return raw.strip(), None, None
    title = match["title"]
    alternatives: list[str] = []
    while (paren := _TRAILING_PARENS_RE.match(title)) is not None and paren["inner"].strip():
        alternatives.append(paren["inner"].strip())
        title = paren["head"]
    alt = _move_article(alternatives[-1]) if alternatives else None
    return _move_article(title.strip()), int(match["year"]), alt


def parse_movies(path: Path | str) -> Iterator[Movie]:
    """Yield movies from ``movies.csv``."""
    for row in _rows(path):
        title, year, alt_title = _split_title(row["title"])
        raw_genres = row["genres"].strip()
        genres = () if raw_genres in ("", _NO_GENRES) else tuple(raw_genres.split("|"))
        yield Movie(int(row["movieId"]), title, year, genres, alt_title)


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
