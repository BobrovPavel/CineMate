from cinemate.services.search import SearchCache
from cinemate.tmdb import TmdbSearchItem

ITEM = [TmdbSearchItem("movie", 1, "A", None, None, None)]


def test_cache_expires_after_ttl():
    now = [0.0]
    cache = SearchCache(ttl=100, clock=lambda: now[0])
    cache.put(("a", "en-US", 1), ITEM)
    now[0] = 99
    assert cache.get(("a", "en-US", 1)) == ITEM
    now[0] = 100
    assert cache.get(("a", "en-US", 1)) is None


def test_cache_evicts_least_recently_used():
    cache = SearchCache(max_entries=2)
    cache.put(("a",), ITEM)
    cache.put(("b",), ITEM)
    cache.get(("a",))
    cache.put(("c",), ITEM)
    assert cache.get(("b",)) is None
    assert cache.get(("a",)) == ITEM
    assert cache.get(("c",)) == ITEM
