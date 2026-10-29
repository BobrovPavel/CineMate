"""Load the TMDB catalog into the database from the daily ID exports (no key needed for those).

TMDB publishes ``movie_ids_MM_DD_YYYY.json.gz`` and ``tv_series_ids_MM_DD_YYYY.json.gz``: gzip,
one JSON object per line. New pairs get one details request each (``fetch_many``, several at a
time; the database is written by the calling thread), most popular first, so an interrupted
run has already stored the best part. Rerunning continues: pairs that are in ``movies`` are
skipped.
"""

import gzip
import json
import os
import time
import zlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import bindparam, select, update
from sqlalchemy.orm import Session

from cinemate.db.catalog import movie_from_details
from cinemate.db.models import Movie
from cinemate.tmdb import DEFAULT_WORKERS, HttpGet, TmdbClient, fetch_many, urllib_get

EXPORT_BASE = "https://files.tmdb.org/p/exports"
EXPORT_PREFIX = {"movie": "movie_ids", "tv": "tv_series_ids"}
DEFAULT_EXPORT_DIR = Path("data/tmdb_exports")
COMMIT_EVERY = 500
PROGRESS_EVERY = 1000
UPDATE_BATCH = 1000

Progress = Callable[[int, int, float, float | None], None]


class CatalogSyncError(Exception):
    """The export could not be obtained or read."""


@dataclass(frozen=True)
class SyncStats:
    in_export: int = 0
    skipped_adult: int = 0
    skipped_video: int = 0
    skipped_low_popularity: int = 0
    already_present: int = 0
    popularity_updated: int = 0
    added: int = 0
    not_found: int = 0
    remaining: int = 0


def export_name(tmdb_type: str, day: date) -> str:
    return f"{EXPORT_PREFIX[tmdb_type]}_{day:%m_%d_%Y}.json.gz"


def fetch_export(
    tmdb_type: str, day: date, export_dir: Path, http_get: HttpGet = urllib_get
) -> Path | None:
    """Path of the export for ``day`` in ``export_dir``, downloading it if absent.

    ``None`` if TMDB has not published it (404). An already downloaded file is not fetched again.
    """
    path = export_dir / export_name(tmdb_type, day)
    if path.exists():
        return path
    status, body = http_get(f"{EXPORT_BASE}/{path.name}")
    if status == 404:
        return None
    if status != 200:
        raise CatalogSyncError(f"TMDB export {path.name} returned HTTP {status}")
    export_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(body)
    os.replace(tmp, path)  # a half-written file never looks like a finished export
    return path


def obtain_export(
    tmdb_type: str, day: date, export_dir: Path, http_get: HttpGet = urllib_get
) -> Path:
    """The export for ``day``, else for the day before (it is published in the UTC morning)."""
    for candidate in (day, day - timedelta(days=1)):
        path = fetch_export(tmdb_type, candidate, export_dir, http_get)
        if path is not None:
            return path
    raise CatalogSyncError(f"no TMDB {tmdb_type} export for {day} or the day before")


def read_export(path: Path) -> Iterator[dict]:
    """Records of an export, streamed; blank and malformed lines are skipped."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and isinstance(record.get("id"), int):
                    yield record
    except (OSError, EOFError, zlib.error) as exc:
        raise CatalogSyncError(
            f"cannot read {path} ({type(exc).__name__}); delete the file to download it again"
        ) from None


def _popularity(record: dict) -> float:
    value = record.get("popularity")
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def sync_catalog(
    session: Session,
    client: TmdbClient,
    *,
    types: Sequence[str] = ("movie", "tv"),
    min_popularity: float = 0.0,
    include_video: bool = False,
    limit: int | None = None,
    workers: int = DEFAULT_WORKERS,
    day: date | None = None,
    export_dir: Path = DEFAULT_EXPORT_DIR,
    http_get: HttpGet | None = None,
    progress: Progress | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SyncStats:
    """Add the pairs of the TMDB exports that are not in ``movies`` yet.

    ``adult`` records are always skipped; ``video`` ones (movies) unless ``include_video``;
    records below ``min_popularity`` are skipped. New pairs go in by descending popularity,
    at most ``limit`` of them per run (``remaining`` counts the rest), fetched by ``workers``
    threads. ``tmdb_popularity`` of
    pairs already stored is refreshed from the export without any TMDB request. A 404 on
    details counts as ``not_found``. Progress is committed every ``COMMIT_EVERY`` movies and
    whenever the run ends, also with ``TmdbError`` or ``KeyboardInterrupt``;
    ``progress(done, total, per_second, eta_seconds)`` is called every ``PROGRESS_EVERY``.
    """
    day = day or datetime.now(UTC).date()
    http_get = http_get or urllib_get
    paths = {t: obtain_export(t, day, export_dir, http_get) for t in types}

    present = {
        (tmdb_type, tmdb_id)
        for tmdb_type, tmdb_id in session.execute(
            select(Movie.tmdb_type, Movie.tmdb_id).where(Movie.tmdb_id.is_not(None))
        )
    }
    in_export = adult = video = low = already = 0
    refresh: list[dict] = []
    fresh: list[tuple[float, str, int]] = []
    for tmdb_type, path in paths.items():
        for record in read_export(path):
            in_export += 1
            if record.get("adult") is True:
                adult += 1
                continue
            pop = _popularity(record)
            if (tmdb_type, record["id"]) in present:
                already += 1
                refresh.append({"t": tmdb_type, "i": record["id"], "p": pop})
            elif record.get("video") is True and not include_video:
                video += 1
            elif pop < min_popularity:
                low += 1
            else:
                fresh.append((pop, tmdb_type, record["id"]))

    stmt = (
        update(Movie)
        .where(Movie.tmdb_type == bindparam("t"), Movie.tmdb_id == bindparam("i"))
        .values(tmdb_popularity=bindparam("p"))
    )
    connection = session.connection()  # Core executemany: a plain WHERE, no ORM bulk-by-pk
    for start in range(0, len(refresh), UPDATE_BATCH):
        connection.execute(stmt, refresh[start : start + UPDATE_BATCH])
    session.commit()

    fresh.sort(key=lambda r: (-r[0], r[1], r[2]))
    todo = fresh if limit is None else fresh[:limit]
    remaining = len(fresh) - len(todo)

    added = not_found = 0
    started = clock()
    try:
        popularity = {(tmdb_type, tmdb_id): pop for pop, tmdb_type, tmdb_id in todo}
        fetched = fetch_many(client, ((t, i) for _, t, i in todo), workers)
        for done, (pair, details) in enumerate(fetched, start=1):
            if details is None:
                not_found += 1
            else:
                movie_from_details(session, details).tmdb_popularity = popularity[pair]
                added += 1
            if done % COMMIT_EVERY == 0:
                session.commit()
            if progress is not None and done % PROGRESS_EVERY == 0:
                elapsed = clock() - started
                rate = done / elapsed if elapsed > 0 else 0.0
                progress(done, len(todo), rate, (len(todo) - done) / rate if rate else None)
    finally:
        session.commit()
    return SyncStats(
        in_export, adult, video, low, already, len(refresh), added, not_found, remaining
    )
