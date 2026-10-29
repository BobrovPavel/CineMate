import threading

from fastapi.testclient import TestClient

from cinemate.api.app import create_app
from cinemate.db.models import POOLS


def _wait(event: threading.Event) -> None:
    assert event.wait(5), "timed out"


def test_pools_are_built_at_startup_without_requests():
    app = create_app("sqlite:///:memory:")
    store = app.state.matrix_store
    built = threading.Event()
    loaded: list[str] = []

    def load(pool):
        loaded.append(pool)
        if len(loaded) == len(POOLS):
            built.set()
        return store.__class__._load(store, pool)

    store._load = load
    with TestClient(app):
        _wait(built)
    assert sorted(loaded) == sorted(POOLS)


def test_request_during_warmup_waits_for_same_build():
    app = create_app("sqlite:///:memory:")
    store = app.state.matrix_store
    started, release = threading.Event(), threading.Event()
    calls: list[str] = []
    original = store._load

    def load(pool):
        calls.append(pool)
        started.set()
        _wait(release)
        return original(pool)

    store._load = load
    with TestClient(app):
        _wait(started)
        results: list = []
        getter = threading.Thread(target=lambda: results.append(store.get(POOLS[0])))
        getter.start()
        getter.join(0.2)
        assert getter.is_alive()  # waits on the build already in progress
        release.set()
        getter.join(5)
        assert not getter.is_alive()
        store.warm(POOLS)  # joins any remaining build
    assert len(results) == 1
    assert sorted(calls) == sorted(POOLS)  # one build per pool, none duplicated


def test_warmup_failure_does_not_break_startup_or_next_request():
    app = create_app("sqlite:///:memory:")
    store = app.state.matrix_store
    failed = threading.Event()
    original = store._load
    state = {"fail": True}

    def load(pool):
        if state["fail"]:
            if pool == POOLS[-1]:
                failed.set()
            raise RuntimeError("boom")
        return original(pool)

    store._load = load
    with TestClient(app) as client:
        _wait(failed)
        assert client.get("/api/health").status_code == 200
        state["fail"] = False
        assert store.get(POOLS[0]).user_ids == []


def test_warm_matrices_false_builds_nothing():
    app = create_app("sqlite:///:memory:", warm_matrices=False)
    store = app.state.matrix_store
    calls: list[str] = []
    store._load = lambda pool: calls.append(pool)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
    assert calls == []
