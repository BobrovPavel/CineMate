import random
import threading
import time

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from cinemate.api.app import create_app, resolve_matrix_rebuild_seconds
from cinemate.config import RecommenderSettings
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, User
from cinemate.db.session import create_all, make_engine
from cinemate.services.recommendations import get_recommendations
from cinemate.services.users import set_rating


@pytest.fixture
def engine():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return engine


@pytest.fixture
def factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def _seed(factory, ratings):
    with factory() as s:
        for uid in {u for u, _, _ in ratings}:
            if s.get(User, uid) is None:
                s.add(User(id=uid))
        for mid in {m for _, m, _ in ratings}:
            if s.get(Movie, mid) is None:
                s.add(Movie(id=mid, title=f"m{mid}"))
        s.flush()
        s.add_all(Rating(user_id=u, movie_id=m, value=v) for u, m, v in ratings)
        s.commit()


def _wait(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_invalidate_does_not_read_the_database(engine, factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory, rebuild_interval=3600)
    first = store.get()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    store.invalidate()
    assert store.get() is first
    assert statements == []


def test_background_rebuild_swaps_matrix(factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory, rebuild_interval=0)
    first = store.get()
    _seed(factory, [(2, 20, -1)])
    store.invalidate()
    assert store.get() is first or store.get().user_ids == [1, 2]
    assert _wait(lambda: store.get().user_ids == [1, 2])
    assert store.get().movie_ids == [10, 20]


def test_not_rebuilt_before_interval(factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory, rebuild_interval=3600)
    first = store.get()
    _seed(factory, [(2, 20, -1)])
    store.invalidate()
    time.sleep(0.05)
    assert store.get() is first


def test_get_does_not_block_during_rebuild(factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory, rebuild_interval=0)
    first = store.get()
    started, release = threading.Event(), threading.Event()
    real_load = store._load

    def slow_load(pool):
        started.set()
        release.wait(5)
        return real_load(pool)

    store._load = slow_load
    _seed(factory, [(2, 20, -1)])
    store.invalidate()
    assert store.get() is first  # starts the rebuild
    assert started.wait(5)
    assert store.get() is first  # rebuild is stuck, readers still get the old matrix
    assert store.get() is first
    release.set()
    assert _wait(lambda: store.get() is not first)
    assert store.get().user_ids == [1, 2]


def test_one_rebuild_at_a_time(factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory, rebuild_interval=0)
    store.get()
    calls = []
    release = threading.Event()
    real_load = store._load

    def slow_load(pool):
        calls.append(pool)
        release.wait(5)
        return real_load(pool)

    store._load = slow_load
    store.invalidate()
    for _ in range(5):
        store.get()
    assert _wait(lambda: len(calls) == 1)
    time.sleep(0.05)
    assert len(calls) == 1
    release.set()


def test_failed_rebuild_keeps_old_matrix(factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory, rebuild_interval=0)
    first = store.get()
    attempted = threading.Event()

    def broken(pool):
        attempted.set()
        raise RuntimeError("db down")

    store._load = broken
    store.invalidate()
    assert store.get() is first
    assert attempted.wait(5)
    assert store.get() is first


def test_invalidate_during_rebuild_stays_stale(factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory, rebuild_interval=3600)
    store.get()
    real_load = store._load

    def load_then_invalidate(pool):
        result = real_load(pool)
        store.invalidate(pool)  # a rating arrives while the load is running
        return result

    store._load = load_then_invalidate
    store.rebuild_now()
    assert "world" in store._stale


def test_first_get_builds_synchronously(factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory, rebuild_interval=3600)
    assert store.get().user_ids == [1]


def test_negative_interval_rejected(factory):
    with pytest.raises(ValueError):
        MatrixStore(factory, rebuild_interval=-1)


def test_own_rating_counts_without_rebuild(factory):
    # user 1 likes 1..5; users 2..4 like 1..5 and 6; user 1's new like of 7 must show at once
    ratings = [(u, m, 1) for u in range(1, 5) for m in range(1, 6)]
    ratings += [(u, 6, 1) for u in range(2, 5)] + [(u, 7, 1) for u in range(2, 5)]
    ratings += [(5, 8, 1)]
    _seed(factory, ratings)
    with factory() as s:
        s.add(Movie(id=9, title="m9"))
        s.commit()
    store = MatrixStore(factory, rebuild_interval=3600)
    settings = RecommenderSettings(min_user_ratings=5, min_overlap=1)
    with factory() as s:
        user = s.get(User, 1)
        before = {i.movie.id for i in get_recommendations(s, store, user, settings=settings).items}
        assert before == {6, 7}
        matrix = store.get()
        set_rating(s, user, 6, 1, store=store)
        s.commit()
        assert store.get() is matrix  # still the old matrix
        after = {i.movie.id for i in get_recommendations(s, store, user, settings=settings).items}
    assert after == {7}


def test_rating_of_unknown_column_is_ignored_and_new_user_row_added(factory):
    _seed(factory, [(1, 10, 1), (1, 11, 1), (2, 10, 1), (2, 11, 1), (2, 12, 1)])
    store = MatrixStore(factory, rebuild_interval=3600)
    store.get()
    with factory() as s:
        s.add_all([User(id=3), Movie(id=99, title="new")])
        s.flush()
        s.add_all(
            [Rating(user_id=3, movie_id=10, value=1), Rating(user_id=3, movie_id=99, value=1)]
        )
        s.commit()
        settings = RecommenderSettings(min_user_ratings=1, min_overlap=1)
        result = get_recommendations(
            s, store, s.get(User, 3), settings=settings, rng=random.Random(0)
        )
    assert result.strategy == "collaborative"
    assert {i.movie.id for i in result.items} == {11, 12}


def test_resolve_matrix_rebuild_seconds():
    assert resolve_matrix_rebuild_seconds(None, {}) == 300
    assert resolve_matrix_rebuild_seconds(None, {"MATRIX_REBUILD_SECONDS": "12.5"}) == 12.5
    assert resolve_matrix_rebuild_seconds(0, {"MATRIX_REBUILD_SECONDS": "12"}) == 0
    for bad in ("x", "-1", "nan", "inf"):
        with pytest.raises(ValueError, match="MATRIX_REBUILD_SECONDS"):
            resolve_matrix_rebuild_seconds(None, {"MATRIX_REBUILD_SECONDS": bad})


def test_create_app_passes_interval():
    app = create_app("sqlite:///:memory:", matrix_rebuild_seconds=7)
    assert app.state.matrix_store._rebuild_interval == 7
