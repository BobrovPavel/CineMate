"""Product event log: impressions and reactions shown in recommendation sessions.

Events carry only ids. All functions only ``flush``; the caller commits.
"""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from cinemate.db.models import Event, User

REACTION_TYPES = ("like", "dislike", "watched", "not_interested")
STRATEGIES = ("collaborative", "fallback")


def log_impressions(
    session: Session,
    user: User,
    session_id: str,
    movie_ids: Iterable[int],
    strategy: str | None,
) -> list[Event]:
    """Record one ``impression`` event per shown movie. Empty ``movie_ids`` writes nothing.

    Raises ``ValueError`` for an unknown ``strategy``.
    """
    if strategy is not None and strategy not in STRATEGIES:
        raise ValueError(f"invalid strategy {strategy!r}")
    events = [
        Event(
            user_id=user.id,
            session_id=session_id,
            type="impression",
            movie_id=movie_id,
            strategy=strategy,
        )
        for movie_id in movie_ids
    ]
    session.add_all(events)
    session.flush()
    return events


def log_reaction(session: Session, user: User, session_id: str, movie_id: int, type: str) -> Event:
    """Record a reaction (``like``, ``dislike``, ``watched``, ``not_interested``).

    Raises ``ValueError`` for any other type.
    """
    if type not in REACTION_TYPES:
        raise ValueError(f"invalid reaction type {type!r}")
    event = Event(user_id=user.id, session_id=session_id, type=type, movie_id=movie_id)
    session.add(event)
    session.flush()
    return event
