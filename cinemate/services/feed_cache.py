"""In-memory snapshots of ranked feeds, so a feed session is computed once and paged.

A snapshot is the ranked list for one (user, feed session). The cache is per process: after a
restart snapshots are gone and the feed is recomputed (see the recommendations route).
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

MAX_FEED = 500
FEED_TTL_SECONDS = 30 * 60
MAX_SNAPSHOTS = 2000


@dataclass(frozen=True)
class FeedSnapshot:
    """A ranked feed: ``strategy``, A/B ``variant`` and ``entries`` as (movie id, payload)."""

    strategy: str
    variant: str | None
    entries: list[tuple[int, Any]]


class FeedCache:
    """Thread-safe LRU cache of :class:`FeedSnapshot` keyed by (user id, session id) with a TTL.

    ``get`` refreshes the recency but not the expiry: a snapshot lives ``ttl`` seconds after
    it was stored.
    """

    def __init__(
        self,
        max_size: int = MAX_SNAPSHOTS,
        ttl: float = FEED_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_size = max_size
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[tuple[int, str], tuple[float, FeedSnapshot]] = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def put(self, user_id: int, session_id: str, snapshot: FeedSnapshot) -> None:
        key = (user_id, session_id)
        with self._lock:
            self._items[key] = (self._clock() + self._ttl, snapshot)
            self._items.move_to_end(key)
            while len(self._items) > self._max_size:
                self._items.popitem(last=False)

    def get(self, user_id: int, session_id: str) -> FeedSnapshot | None:
        key = (user_id, session_id)
        with self._lock:
            found = self._items.get(key)
            if found is None:
                return None
            expires, snapshot = found
            if expires <= self._clock():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return snapshot


def take_page(
    entries: list[tuple[int, Any]], offset: int, limit: int, skip: set[int]
) -> tuple[list[Any], int, bool]:
    """Up to ``limit`` payloads from ``entries[offset:]`` not in ``skip``.

    Returns the payloads, the next offset and whether any non-skipped entry remains after it.
    """
    page: list[Any] = []
    pos = max(offset, 0)
    while pos < len(entries) and len(page) < limit:
        movie_id, payload = entries[pos]
        pos += 1
        if movie_id not in skip:
            page.append(payload)
    has_more = any(movie_id not in skip for movie_id, _ in entries[pos:])
    return page, pos, has_more
