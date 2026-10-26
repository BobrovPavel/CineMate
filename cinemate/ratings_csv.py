"""Reader for an external ratings CSV (user_id, movie_id, user_rating on a 1-10 scale)."""

import csv
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from pathlib import Path

from cinemate.movielens import Rating

CSV_MIN_RATINGS = 20
_REQUIRED = ("user_id", "movie_id", "user_rating")
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
    movie_id: int
    user_rating: int
    title_ru: str | None = None
    title_original: str | None = None
    type: str | None = None
    year: int | None = None
    genres: tuple[str, ...] = ()
    kp_rating: float | None = None


def _text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _parse_row(raw: dict[str, str | None]) -> CsvRow:
    try:
        user_id = int((raw["user_id"] or "").strip())
        movie_id = int((raw["movie_id"] or "").strip())
    except ValueError:
        raise ValueError("user_id and movie_id must be integers") from None
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
        movie_id=movie_id,
        user_rating=rating,
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
        for row in reader:
            try:
                yield _parse_row(row)
            except ValueError as exc:
                raise ValueError(f"line {reader.line_num}: {exc}") from None


def load_ratings(path: Path | str, types: Collection[str] | None = None) -> list[Rating]:
    """Load ratings; with ``types`` keep only rows of those types (case-insensitive).

    A repeated (user, movie) pair keeps the last row. Raises ``ValueError`` if nothing is left.
    """
    wanted = {t.strip().lower() for t in types} if types is not None else None
    latest: dict[tuple[int, int], Rating] = {}
    for row in read_rows(path):
        if wanted is not None and (row.type is None or row.type.lower() not in wanted):
            continue
        latest[(row.user_id, row.movie_id)] = Rating(
            row.user_id, row.movie_id, float(row.user_rating)
        )
    if not latest:
        raise ValueError("no ratings found in the file")
    return list(latest.values())
