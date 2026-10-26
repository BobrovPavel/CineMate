"""Reader for an external ratings CSV.

Columns: ``user_id``, ``user_rating`` (1-10) and per movie at least one of ``kp_id`` (Kinopoisk
id; the old name ``movie_id`` is a synonym), ``tmdb_type`` + ``tmdb_id``, ``imdb_id``.
"""

import csv
import re
import warnings
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from pathlib import Path

from cinemate.movielens import Rating

CSV_MIN_RATINGS = 20
_REQUIRED = ("user_id", "user_rating")
_MOVIE_ID_COLUMNS = ("kp_id", "movie_id", "tmdb_id", "imdb_id")
_IMDB_ID = re.compile(r"tt\d+")
_OPTIONAL = (
    "title_ru",
    "title_original",
    "type",
    "year",
    "genres",
    "kp_rating",
)


@dataclass(frozen=True)
class CsvRow:
    user_id: int
    user_rating: int
    kp_id: int | None = None
    tmdb_type: str | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    title_ru: str | None = None
    title_original: str | None = None
    type: str | None = None
    year: int | None = None
    genres: tuple[str, ...] = ()
    kp_rating: float | None = None


def _text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _int(raw: dict[str, str | None], column: str) -> int | None:
    text = _text(raw.get(column))
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{column} must be an integer") from None


def _parse_row(raw: dict[str, str | None], kp_column: str) -> CsvRow:
    user_id = _int(raw, "user_id")
    if user_id is None:
        raise ValueError("user_id must be an integer")
    kp_id = _int(raw, kp_column)
    tmdb_id = _int(raw, "tmdb_id")
    tmdb_type = (_text(raw.get("tmdb_type")) or "").lower() or None
    imdb_id = _text(raw.get("imdb_id"))
    if tmdb_type is not None and tmdb_type not in ("movie", "tv"):
        raise ValueError("tmdb_type must be movie or tv")
    if (tmdb_type is None) != (tmdb_id is None):
        raise ValueError("tmdb_type and tmdb_id must be given together")
    if imdb_id is not None and not _IMDB_ID.fullmatch(imdb_id):
        raise ValueError("imdb_id must look like tt1234567")
    if kp_id is None and tmdb_id is None and imdb_id is None:
        raise ValueError("a row needs kp_id, tmdb_id or imdb_id")
    try:
        rating = int((raw["user_rating"] or "").strip())
    except ValueError:
        raise ValueError("user_rating must be an integer from 1 to 10") from None
    if not 1 <= rating <= 10:
        raise ValueError("user_rating must be an integer from 1 to 10")
    year_text = _text(raw.get("year"))
    kp_text = _text(raw.get("kp_rating"))
    try:
        year = int(year_text) if year_text else None
    except ValueError:
        raise ValueError("year must be an integer") from None
    try:
        kp_rating = float(kp_text) if kp_text else None
    except ValueError:
        raise ValueError("kp_rating must be a number") from None
    genres_text = _text(raw.get("genres"))
    genres = tuple(g.strip() for g in genres_text.split(",") if g.strip()) if genres_text else ()
    return CsvRow(
        user_id=user_id,
        user_rating=rating,
        kp_id=kp_id,
        tmdb_type=tmdb_type,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        title_ru=_text(raw.get("title_ru")),
        title_original=_text(raw.get("title_original")),
        type=_text(raw.get("type")),
        year=year,
        genres=genres,
        kp_rating=kp_rating,
    )


def read_rows(path: Path | str) -> Iterator[CsvRow]:
    """Yield rows of the ratings CSV; ``ValueError`` names a missing column or a bad line."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        for column in _REQUIRED:
            if column not in fields:
                raise ValueError(f"missing required column: {column}")
        if not any(column in fields for column in _MOVIE_ID_COLUMNS):
            raise ValueError("missing movie id column: kp_id, tmdb_id or imdb_id")
        kp_column = "kp_id" if "kp_id" in fields else "movie_id"
        if kp_column == "movie_id" and "movie_id" in fields:
            warnings.warn("column movie_id is deprecated, rename it to kp_id", stacklevel=2)
        for row in reader:
            try:
                yield _parse_row(row, kp_column)
            except ValueError as exc:
                raise ValueError(f"line {reader.line_num}: {exc}") from None


def movie_key(row: CsvRow) -> str:
    """Key of a row's movie: the TMDB pair, else the IMDb id, else the Kinopoisk id."""
    if row.tmdb_id is not None:
        return f"tmdb:{row.tmdb_type}:{row.tmdb_id}"
    if row.imdb_id is not None:
        return f"imdb:{row.imdb_id}"
    return f"kp:{row.kp_id}"


def load_ratings(path: Path | str, types: Collection[str] | None = None) -> list[Rating]:
    """Load ratings; with ``types`` keep only rows of those types (case-insensitive).

    A repeated (user, movie) pair keeps the last row. Raises ``ValueError`` if nothing is left.
    """
    wanted = {t.strip().lower() for t in types} if types is not None else None
    latest: dict[tuple[int, str], Rating] = {}
    for row in read_rows(path):
        if wanted is not None and (row.type is None or row.type.lower() not in wanted):
            continue
        key = movie_key(row)
        latest[(row.user_id, key)] = Rating(row.user_id, key, float(row.user_rating))
    if not latest:
        raise ValueError("no ratings found in the file")
    return list(latest.values())
