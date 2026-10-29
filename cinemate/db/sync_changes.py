"""Keep the stored TMDB catalog fresh from the daily ``/changes`` feeds.

For each type the period runs from ``catalog_sync.changes_synced_until`` (else ``since``, else one
day back) to now. Every changed pair is refreshed if it is in ``movies`` and created if not.
``changes_synced_until`` moves only once the whole period of a type is processed, so an
interrupted run repeats the period; pairs already fetched since the start day are skipped then,
which is also why a second run on the same day asks TMDB for almost nothing.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from cinemate.db.catalog import find_movie, movie_from_details
from cinemate.db.enrich import apply_details
from cinemate.db.models import CatalogSync, Movie
from cinemate.tmdb import DEFAULT_WORKERS, TmdbClient, fetch_many

DEFAULT_LOOKBACK = timedelta(days=1)
MAX_PERIOD = timedelta(days=90)
COMMIT_EVERY = 500


class ChangesPeriodTooLong(Exception):
    """The period to catch up on is longer than ``MAX_PERIOD``; use the full export instead."""


@dataclass(frozen=True)
class ChangesStats:
    start: datetime
    end: datetime
    changed: int = 0
    updated: int = 0
    added: int = 0
    not_found: int = 0
    skipped_low_popularity: int = 0
    up_to_date: int = 0
    remaining: int = 0


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def sync_changes(
    session: Session,
    client: TmdbClient,
    *,
    types: Sequence[str] = ("movie", "tv"),
    since: datetime | None = None,
    min_popularity: float = 0.0,
    limit: int | None = None,
    workers: int = DEFAULT_WORKERS,
    now: datetime | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> ChangesStats:
    """Apply the TMDB changes of every type in ``types`` since its last sync.

    Existing pairs are updated by the ``enrich-movies`` rules (``apply_details``) and get
    ``tmdb_popularity``; new pairs below ``min_popularity`` (from the details) are not created;
    404 counts as ``not_found``. ``limit`` caps the details requests of the whole run; when it
    cuts a type short, that type's ``changes_synced_until`` stays put. Details are fetched by
    ``workers`` threads, the database is written by the calling one. Progress is committed
    every ``COMMIT_EVERY`` records and when the run ends, also with ``TmdbError``.
    Raises ``ChangesPeriodTooLong`` before any request if a period exceeds 90 days.
    """
    end = _aware(now) if now else datetime.now(UTC)
    states = {t: session.get(CatalogSync, t) for t in types}
    starts = {}
    for tmdb_type, state in states.items():
        if state is not None:
            starts[tmdb_type] = _aware(state.changes_synced_until)
        else:
            starts[tmdb_type] = _aware(since) if since else end - DEFAULT_LOOKBACK
        if end - starts[tmdb_type] > MAX_PERIOD:
            raise ChangesPeriodTooLong(
                f"{tmdb_type}: changes since {starts[tmdb_type]:%Y-%m-%d} are over "
                f"{MAX_PERIOD.days} days old"
            )

    counts = dict.fromkeys(
        ("changed", "updated", "added", "not_found", "low", "fresh", "remaining"), 0
    )
    budget = limit
    try:
        for tmdb_type in types:
            start = starts[tmdb_type]
            day_start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            ids = list(client.changes(tmdb_type, start.date(), end.date()))
            counts["changed"] += len(ids)
            complete = True
            todo: dict[int, Movie | None] = {}
            for done, tmdb_id in enumerate(ids, start=1):
                movie = find_movie(session, tmdb=(tmdb_type, tmdb_id))
                if (
                    movie is not None
                    and movie.tmdb_fetched_at is not None
                    and _aware(movie.tmdb_fetched_at) >= day_start
                ):
                    counts["fresh"] += 1
                    continue
                if budget is not None and budget <= 0:
                    counts["remaining"] += len(ids) - done + 1
                    complete = False
                    break
                if budget is not None:
                    budget -= 1
                todo[tmdb_id] = movie
            pairs = ((tmdb_type, tmdb_id) for tmdb_id in todo)
            for done, ((_, tmdb_id), details) in enumerate(
                fetch_many(client, pairs, workers), start=1
            ):
                movie = todo[tmdb_id]
                if details is None:
                    counts["not_found"] += 1
                elif movie is not None:
                    apply_details(session, movie, details)
                    if details.popularity is not None:
                        movie.tmdb_popularity = details.popularity
                    counts["updated"] += 1
                elif details.popularity is not None and details.popularity < min_popularity:
                    counts["low"] += 1
                else:
                    movie_from_details(session, details)
                    counts["added"] += 1
                if done % COMMIT_EVERY == 0:
                    session.commit()
                    if progress is not None:
                        progress(tmdb_type, done, len(todo))
            if complete:
                state = states[tmdb_type]
                if state is None:
                    session.add(CatalogSync(tmdb_type=tmdb_type, changes_synced_until=end))
                else:
                    state.changes_synced_until = end
                session.commit()
    finally:
        session.commit()
    first = min(starts.values()) if starts else end
    return ChangesStats(
        first,
        end,
        counts["changed"],
        counts["updated"],
        counts["added"],
        counts["not_found"],
        counts["low"],
        counts["fresh"],
        counts["remaining"],
    )
