"""Ratings of other platforms: the IMDb dataset import and batch upserts into ``external_ratings``.

IMDb data comes only from the official non-commercial datasets (https://datasets.imdbws.com/);
see "Данные и лицензии" in the README.
"""

import gzip
import tempfile
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from cinemate.db.models import ExternalRating, MovieExternalId

IMDB_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
IMDB_RATINGS_NAME = "title.ratings.tsv.gz"
DEFAULT_IMDB_DIR = Path("data") / "imdb"
BATCH_SIZE = 5_000


@dataclass(frozen=True)
class ImdbImportStats:
    rows: int
    matched: int
    updated: int


def _download(url: str, target: Path) -> None:
    urllib.request.urlretrieve(url, target)


def ensure_imdb_ratings(dest: Path = DEFAULT_IMDB_DIR, today: date | None = None) -> Path:
    """Path of ``title.ratings.tsv.gz`` in ``dest``; downloaded unless it was fetched today."""
    target = dest / IMDB_RATINGS_NAME
    today = today or date.today()
    if target.exists() and date.fromtimestamp(target.stat().st_mtime) == today:
        return target
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        part = Path(tmp) / IMDB_RATINGS_NAME
        _download(IMDB_RATINGS_URL, part)
        part.replace(target)  # a failed download leaves the previous file in place
    return target


def read_imdb_ratings(path: Path | str) -> Iterator[tuple[str, float, int]]:
    """Stream ``(tconst, averageRating, numVotes)`` from the gzip TSV; ``ValueError`` if the
    header lacks a column or a line is malformed."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        header = f.readline().rstrip("\r\n").split("\t")
        try:
            columns = [header.index(c) for c in ("tconst", "averageRating", "numVotes")]
        except ValueError:
            raise ValueError("expected columns tconst, averageRating, numVotes") from None
        width = max(columns) + 1
        for number, line in enumerate(f, start=2):
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) < width:
                raise ValueError(f"line {number}: too few columns")
            try:
                yield parts[columns[0]], float(parts[columns[1]]), int(parts[columns[2]])
            except ValueError:
                raise ValueError(f"line {number}: bad rating or vote count") from None


def upsert_external_ratings(
    session: Session,
    source: str,
    ratings: Mapping[int, tuple[float, int | None]],
    now: datetime | None = None,
) -> int:
    """Write ``movie_id -> (value, votes)`` for ``source`` in batches; returns the number of rows
    inserted or changed (a row that already has the same value and votes is left alone)."""
    now = now or datetime.now(UTC)
    existing: dict[int, tuple[float, int | None]] = {}
    movie_ids = list(ratings)
    for start in range(0, len(movie_ids), BATCH_SIZE):
        chunk = movie_ids[start : start + BATCH_SIZE]
        for movie_id, value, votes in session.execute(
            select(ExternalRating.movie_id, ExternalRating.value, ExternalRating.votes).where(
                ExternalRating.source == source, ExternalRating.movie_id.in_(chunk)
            )
        ):
            existing[movie_id] = (value, votes)
    new = [
        {"movie_id": m, "source": source, "value": v, "votes": n, "updated_at": now}
        for m, (v, n) in ratings.items()
        if m not in existing
    ]
    changed = [
        {"movie_id": m, "source": source, "value": v, "votes": n, "updated_at": now}
        for m, (v, n) in ratings.items()
        if m in existing and existing[m] != (v, n)
    ]
    for start in range(0, len(new), BATCH_SIZE):
        session.execute(insert(ExternalRating), new[start : start + BATCH_SIZE])
    for start in range(0, len(changed), BATCH_SIZE):
        for row in changed[start : start + BATCH_SIZE]:
            session.execute(
                update(ExternalRating)
                .where(ExternalRating.movie_id == row["movie_id"], ExternalRating.source == source)
                .values(value=row["value"], votes=row["votes"], updated_at=now)
            )
    session.flush()
    return len(new) + len(changed)


def import_imdb_ratings(session: Session, path: Path | str) -> ImdbImportStats:
    """Store the IMDb rating of every movie that has an IMDb id (``movie_external_ids``).

    The file is read as a stream. A movie with several IMDb ids keeps the rating with the most
    votes. Re-running with the same file changes nothing. The caller commits.
    """
    movie_by_imdb = dict(
        session.execute(
            select(MovieExternalId.external_id, MovieExternalId.movie_id).where(
                MovieExternalId.source == "imdb"
            )
        ).all()
    )
    rows = 0
    best: dict[int, tuple[float, int]] = {}
    for tconst, value, votes in read_imdb_ratings(path):
        rows += 1
        movie_id = movie_by_imdb.get(tconst)
        if movie_id is None:
            continue
        current = best.get(movie_id)
        if current is None or votes > current[1]:
            best[movie_id] = (value, votes)
    updated = upsert_external_ratings(session, "imdb", best)
    return ImdbImportStats(rows=rows, matched=len(best), updated=updated)
