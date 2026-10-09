"""Product metrics computed from the event log.

Definitions:

* A **session** is a unique ``session_id`` that has at least one ``impression`` event.
  Events of a ``session_id`` without any impression (e.g. a stray ``like``) do not
  create a session.
* A session is **good** if it also contains at least one ``like`` event.
* A session's **strategy** is the strategy recorded on its impressions (the first one
  by id); sessions without a recorded strategy are grouped under ``"unknown"``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.models import Event

RETENTION_WINDOW = timedelta(days=7)
UNKNOWN_STRATEGY = "unknown"


@dataclass(frozen=True)
class SessionRate:
    total: int
    good: int
    rate: float


def _rate(total: int, good: int) -> SessionRate:
    return SessionRate(total=total, good=good, rate=good / total if total else 0.0)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _session_stats(session: Session, since: datetime | None) -> dict[str, tuple[str, bool]]:
    """Map each session id to ``(strategy, has_like)`` for sessions with an impression."""
    stmt = select(Event.session_id, Event.type, Event.strategy).order_by(Event.id)
    if since is not None:
        stmt = stmt.where(Event.created_at >= since)
    strategies: dict[str, str] = {}
    liked: set[str] = set()
    for session_id, type_, strategy in session.execute(stmt):
        if type_ == "impression":
            strategies.setdefault(session_id, strategy or UNKNOWN_STRATEGY)
        elif type_ == "like":
            liked.add(session_id)
    return {sid: (strategy, sid in liked) for sid, strategy in strategies.items()}


def good_session_rate(session: Session, since: datetime | None = None) -> SessionRate:
    """Share of sessions with at least one ``like``; ``rate`` is 0.0 when there are none.

    ``since`` keeps only events created at or after that moment.
    """
    stats = _session_stats(session, since)
    return _rate(len(stats), sum(1 for _, has_like in stats.values() if has_like))


def good_session_rate_by_strategy(
    session: Session, since: datetime | None = None
) -> dict[str, SessionRate]:
    """Same as :func:`good_session_rate`, split by the session's recommendation strategy."""
    totals: dict[str, list[int]] = {}
    for strategy, has_like in _session_stats(session, since).values():
        counts = totals.setdefault(strategy, [0, 0])
        counts[0] += 1
        counts[1] += has_like
    return {s: _rate(total, good) for s, (total, good) in sorted(totals.items())}


def retention_7d(session: Session, now: datetime | None = None) -> float:
    """Share of users who had another event within 7 days after their first event.

    Only users whose first event is at least 7 days old at ``now`` are counted;
    returns 0.0 when there are no such users.
    """
    now = _aware(now) if now is not None else datetime.now(UTC)
    times: dict[int, list[datetime]] = {}
    for user_id, created_at in session.execute(
        select(Event.user_id, Event.created_at).order_by(Event.created_at)
    ):
        times.setdefault(user_id, []).append(_aware(created_at))
    eligible = retained = 0
    for stamps in times.values():
        first = stamps[0]
        if now - first < RETENTION_WINDOW:
            continue
        eligible += 1
        if any(first < t <= first + RETENTION_WINDOW for t in stamps[1:]):
            retained += 1
    return retained / eligible if eligible else 0.0
