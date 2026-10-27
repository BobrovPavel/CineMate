import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from cinemate.api.app import create_app
from cinemate.config import RecommenderSettings
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, User
from cinemate.db.session import create_all, make_engine
from cinemate.services.onboarding import onboarding_for_user
from cinemate.services.recommendations import get_recommendations
from cinemate.services.users import (
    create_session_user,
    pool_from_accept_language,
    set_rating,
)


@pytest.mark.parametrize(
    ("header", "pool"),
    [
        ("ru", "ru"),
        ("ru-RU", "ru"),
        ("RU-ru", "ru"),
        ("ru-RU,ru;q=0.9,en;q=0.8", "ru"),
        ("en-US,ru;q=0.5", "world"),
        ("en", "world"),
        ("ru;q=0", "world"),
        ("rus", "world"),
        ("*", "world"),
        ("", "world"),
        (None, "world"),
        ("ru;q=abc", "world"),
    ],
)
def test_pool_from_accept_language(header, pool):
    assert pool_from_accept_language(header) == pool


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return sessionmaker(engine)


def _seed(factory):
    """Pool ru: users 1-3 like movies 1-3; pool world: users 4-6 like movies 4-6."""
    with factory() as s:
        s.add_all(Movie(id=i, title=f"m{i}", genres=["g"]) for i in range(1, 8))
        for uid in range(1, 7):
            s.add(User(id=uid, pool="ru" if uid <= 3 else "world"))
        s.flush()
        for uid in range(1, 4):
            s.add_all(Rating(user_id=uid, movie_id=m, value=1) for m in (1, 2, 3))
        for uid in range(4, 7):
            s.add_all(Rating(user_id=uid, movie_id=m, value=1) for m in (4, 5, 6))
        s.commit()


def test_matrices_are_independent(factory):
    _seed(factory)
    store = MatrixStore(factory)
    ru, world = store.get("ru"), store.get("world")
    assert ru.user_ids == [1, 2, 3]
    assert ru.movie_ids == [1, 2, 3]
    assert world.user_ids == [4, 5, 6]
    assert world.movie_ids == [4, 5, 6]


def test_invalidate_touches_only_own_pool(factory):
    _seed(factory)
    store = MatrixStore(factory)
    ru, world = store.get("ru"), store.get("world")
    store.invalidate("ru")
    store.rebuild_now()  # rebuilds every cached pool, stale or not
    assert store.get("world") is not world
    assert store.get("ru") is not ru
    ru, world = store.get("ru"), store.get("world")
    store.invalidate("ru")
    store.rebuild_now("ru")
    assert store.get("world") is world
    assert store.get("ru") is not ru


def test_rating_invalidates_only_authors_pool(factory):
    _seed(factory)
    store = MatrixStore(factory)
    ru, world = store.get("ru"), store.get("world")
    with factory() as s:
        set_rating(s, s.get(User, 1), 7, 1, store=store)
        s.commit()
    assert store.get("ru") is ru  # not rebuilt by the request
    store.rebuild_now("ru")
    assert store.get("world") is world
    assert 7 in store.get("ru").movie_ids
    assert 7 not in store.get("world").movie_ids


def test_new_user_gets_pool(factory):
    with factory() as s:
        assert create_session_user(s).pool == "world"
        assert create_session_user(s, "ru").pool == "ru"


def test_recommendations_use_own_pool(factory):
    _seed(factory)
    with factory() as s:
        for uid, wanted in ((1, {1, 2, 3}), (4, {4, 5, 6})):
            user = User(id=uid + 100, pool=s.get(User, uid).pool)
            s.add(user)
            s.flush()
            s.add(Rating(user_id=user.id, movie_id=min(wanted), value=1))
        s.commit()
    store = MatrixStore(factory)
    settings = RecommenderSettings(min_user_ratings=1, min_overlap=1)
    with factory() as s:
        ru = get_recommendations(s, store, s.get(User, 101), settings=settings)
        world = get_recommendations(s, store, s.get(User, 104), settings=settings)
    assert {i.movie.id for i in ru.items} <= {2, 3}
    assert {i.movie.id for i in world.items} <= {5, 6}
    assert ru.items and world.items


def test_fallback_popular_is_per_pool(factory):
    _seed(factory)
    with factory() as s:
        s.add(User(id=50, pool="ru"))
        s.add(User(id=51, pool="world"))
        s.commit()
    store = MatrixStore(factory)
    with factory() as s:
        ru = get_recommendations(s, store, s.get(User, 50))
        world = get_recommendations(s, store, s.get(User, 51))
    assert ru.strategy == world.strategy == "fallback"
    assert {i.movie.id for i in ru.items} == {1, 2, 3}
    assert {i.movie.id for i in world.items} == {4, 5, 6}


def test_onboarding_uses_own_pool(factory):
    _seed(factory)
    with factory() as s:
        s.add_all([User(id=50, pool="ru"), User(id=51, pool="world")])
        s.commit()
    store = MatrixStore(factory)
    with factory() as s:
        ru = onboarding_for_user(s, store, s.get(User, 50))
        world = onboarding_for_user(s, store, s.get(User, 51))
    assert {m.id for m in ru} == {1, 2, 3}
    assert {m.id for m in world} == {4, 5, 6}


@pytest.fixture
def app():
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as s:
        s.add_all(Movie(id=i, title=f"m{i}", genres=["g"]) for i in range(1, 5))
        s.add_all([User(id=1, pool="ru"), User(id=2, pool="world")])
        s.flush()
        s.add_all([Rating(user_id=1, movie_id=1, value=1), Rating(user_id=2, movie_id=2, value=1)])
        s.commit()
    return app


@pytest.mark.parametrize(
    ("header", "pool", "movie"),
    [
        ("ru-RU,ru;q=0.9,en;q=0.8", "ru", 1),
        ("en-US,ru;q=0.5", "world", 2),
        (None, "world", 2),
    ],
)
def test_api_session_pool_and_onboarding(app, header, pool, movie):
    headers = {"Accept-Language": header} if header else {}
    with TestClient(app) as client:
        body = client.post("/api/session", headers=headers).json()
        assert body["pool"] == pool
        cards = client.get("/api/onboarding").json()
        assert [c["movie_id"] for c in cards] == [movie]
        # the pool is fixed once: a later request with another language keeps it
        again = client.post("/api/session", headers={"Accept-Language": "ru"}).json()
        assert again["pool"] == pool


def test_api_rating_updates_only_own_pool(app):
    store = app.state.matrix_store
    with TestClient(app) as client:
        client.post("/api/session", headers={"Accept-Language": "ru"})
        ru = store.get("ru")
        assert client.post("/api/ratings", json={"movie_id": 3, "value": 1}).status_code == 200
        assert store.get("ru") is ru
        store.rebuild_now()
        assert 3 in store.get("ru").movie_ids
        assert 3 not in store.get("world").movie_ids
