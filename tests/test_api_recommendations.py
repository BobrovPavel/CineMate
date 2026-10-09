import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemate.api.app import create_app
from cinemate.db.models import Event, Movie, Rating, User


@pytest.fixture
def app():
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        session.add_all(
            [Movie(id=i, title=f"M{i}", original_title=f"O{i}", year=2000 + i) for i in range(1, 9)]
        )
        for _ in range(6):
            user = User(is_synthetic=True)
            session.add(user)
            session.flush()
            for movie_id in range(1, 8):
                session.add(Rating(user_id=user.id, movie_id=movie_id, value=1))
        session.commit()
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.post("/api/session")
        yield client


def _events(app):
    with app.state.session_factory() as session:
        return list(session.scalars(select(Event)))


def test_requires_session(app):
    with TestClient(app) as client:
        assert client.get("/api/recommendations").status_code == 401
        assert client.get("/api/movies/1").status_code == 401


def test_fallback_for_new_user(app, client):
    body = client.get("/api/recommendations?limit=5").json()
    assert body["strategy"] == "fallback"
    assert 0 < len(body["items"]) <= 5
    assert all(i["liked_by"] == 0 and i["because_of"] == [] for i in body["items"])
    events = _events(app)
    assert len(events) == len(body["items"])
    assert {e.session_id for e in events} == {body["session_id"]}
    assert {e.type for e in events} == {"impression"}
    assert {e.strategy for e in events} == {"fallback"}


def test_collaborative_with_neighbors(app, client):
    for movie_id in range(1, 7):
        assert (
            client.post("/api/ratings", json={"movie_id": movie_id, "value": 1}).status_code == 200
        )
    body = client.get("/api/recommendations").json()
    assert body["strategy"] == "collaborative"
    assert [i["movie"]["id"] for i in body["items"]] == [7]
    item = body["items"][0]
    assert item["liked_by"] > 0
    assert item["because_of"]
    assert item["movie"]["original_title"] == "O7"
    assert {e.strategy for e in _events(app)} == {"collaborative"}


def test_each_call_new_session_id(client):
    first = client.get("/api/recommendations").json()["session_id"]
    second = client.get("/api/recommendations").json()["session_id"]
    assert first != second


@pytest.mark.parametrize("limit", [0, 51, -1])
def test_limit_out_of_range(client, limit):
    assert client.get(f"/api/recommendations?limit={limit}").status_code == 422


def test_movie_detail(client):
    body = client.get("/api/movies/3").json()
    assert body["title"] == "M3"
    assert body["year"] == 2003
    assert set(body) == {
        "id",
        "title",
        "original_title",
        "year",
        "overview",
        "poster_path",
        "genres",
        "runtime",
    }


def test_movie_not_found(client):
    assert client.get("/api/movies/999").status_code == 404
