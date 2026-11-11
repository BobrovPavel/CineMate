from cinemate.services.feed_cache import FeedCache, FeedSnapshot, take_page


def _snap(tag: str = "x") -> FeedSnapshot:
    return FeedSnapshot(strategy="fallback", variant=None, entries=[(1, tag)])


def test_lru_evicts_the_least_recently_used():
    cache = FeedCache(max_size=2)
    cache.put(1, "a", _snap("a"))
    cache.put(1, "b", _snap("b"))
    assert cache.get(1, "a") is not None  # "b" is now the oldest
    cache.put(1, "c", _snap("c"))
    assert len(cache) == 2
    assert cache.get(1, "b") is None
    assert cache.get(1, "a") is not None
    assert cache.get(1, "c") is not None


def test_snapshot_expires_after_ttl():
    now = [0.0]
    cache = FeedCache(ttl=100, clock=lambda: now[0])
    cache.put(1, "a", _snap())
    now[0] = 99
    assert cache.get(1, "a") is not None
    now[0] = 100
    assert cache.get(1, "a") is None
    assert len(cache) == 0


def test_key_includes_user():
    cache = FeedCache()
    cache.put(1, "a", _snap())
    assert cache.get(2, "a") is None


def test_take_page_skips_and_reports_remaining():
    entries = [(i, f"m{i}") for i in range(1, 7)]
    page, nxt, more = take_page(entries, 0, 2, {2})
    assert page == ["m1", "m3"]
    assert (nxt, more) == (3, True)
    page, nxt, more = take_page(entries, nxt, 5, {6})
    assert page == ["m4", "m5"]
    assert (nxt, more) == (6, False)
