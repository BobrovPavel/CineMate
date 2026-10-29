import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemate.api.app import create_app
from cinemate.config import RecommenderSettings
from cinemate.db.features import seed_genres
from cinemate.db.models import Rating, UserCategoryPref
from tests.category_fixtures import CF, MARVEL, MARVEL_CANDIDATES, OTHER, seed


@pytest.fixture
def app():
    app = create_app("sqlite:///:memory:", recommender_settings=RecommenderSettings(**CF))
    seed_genres(app.state.engine)
    with app.state.session_factory() as session:
        seed(session, dislikes=0)
        # users 2..8 rated everything; user 1 is replaced by the session user below
        session.query(Rating).filter(Rating.user_id == 1).delete()
        session.commit()
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        user_id = client.post("/api/session").json()["user_id"]
        with app.state.session_factory() as session:
            for m in range(1, 7):
                session.add(Rating(user_id=user_id, movie_id=m, value=1))
            for m in MARVEL:
                session.add(Rating(user_id=user_id, movie_id=m, value=-1))
            for m in OTHER[:2]:
                session.add(Rating(user_id=user_id, movie_id=m, value=1))
            session.commit()
        yield client


def ids(client, limit=40):
    body = client.get(f"/api/recommendations?limit={limit}").json()
    assert body["strategy"] == "collaborative"
    return [i["movie"]["id"] for i in body["items"]]


def test_requires_session(app):
    with TestClient(app) as client:
        assert client.get("/api/category-prefs").status_code == 401
        body = {"kind": "studio", "key": "1", "show": True}
        assert client.post("/api/category-prefs", json=body).status_code == 401


def test_get_lists_triggered_categories_with_counts(client):
    views = {(v["kind"], v["key"]): v for v in client.get("/api/category-prefs").json()}
    assert views[("studio", "1")] == {
        "kind": "studio",
        "key": "1",
        "name": "Marvel Studios",
        "disliked": 5,
        "rated": 5,
        "show": False,
    }
    assert views[("genre", "28")]["name"] == "Action"
    ru = client.get("/api/category-prefs", headers={"Accept-Language": "ru"}).json()
    assert {v["name"] for v in ru if v["kind"] == "genre"} == {"боевик"}


def test_hidden_then_shown_then_hidden_again(client, app):
    def position_of_candidates():
        feed = ids(client)
        return [feed.index(m) for m in MARVEL_CANDIDATES]

    assert min(position_of_candidates()) >= len(OTHER) - 2  # after the other movies

    for kind, key in (("studio", "1"), ("genre", "28")):
        body = {"kind": kind, "key": key, "show": True}
        assert client.post("/api/category-prefs", json=body).json()["ok"] is True
    assert sorted(position_of_candidates()) == [0, 1, 2]
    shown = {(v["kind"], v["key"]): v["show"] for v in client.get("/api/category-prefs").json()}
    assert shown == {("studio", "1"): True, ("genre", "28"): True}
    with app.state.session_factory() as session:
        assert session.scalar(select(UserCategoryPref.mode)) == "show"

    for kind, key in (("studio", "1"), ("genre", "28")):
        client.post("/api/category-prefs", json={"kind": kind, "key": key, "show": False})
    assert min(position_of_candidates()) >= len(OTHER) - 2
    assert {v["show"] for v in client.get("/api/category-prefs").json()} == {False}


def test_rejects_unknown_kind_and_empty_key(client):
    for body in (
        {"kind": "actor", "key": "1", "show": True},
        {"kind": "studio", "key": "", "show": True},
        {"kind": "studio", "key": "1"},
    ):
        assert client.post("/api/category-prefs", json=body).status_code == 422
