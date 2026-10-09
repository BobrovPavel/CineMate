import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemate.api.app import create_app
from cinemate.db.models import Event, Movie, Rating, SeenMark, User


@pytest.fixture
def app():
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        session.add_all(
            [
                Movie(id=1, title="A", year=1999, poster_path="/a.jpg", genres=["Drama"]),
                Movie(id=2, title="B", genres=["Comedy"]),
                Movie(id=3, title="C"),
            ]
        )
        others = [User(is_synthetic=True) for _ in range(2)]
        session.add_all(others)
        session.flush()
        for i, other in enumerate(others):
            for movie_id in (1, 2, 3):
                value = 1 if (i + movie_id) % 2 else -1
                session.add(Rating(user_id=other.id, movie_id=movie_id, value=value))
        session.commit()
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.post("/api/session")
        yield client


def _events(app):
    with app.state.session_factory() as session:
        return [(e.type, e.movie_id, e.session_id) for e in session.scalars(select(Event))]


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("get", "/api/onboarding", None),
        ("post", "/api/ratings", {"movie_id": 1, "value": 1}),
        ("post", "/api/seen", {"movie_id": 1, "type": "watched"}),
    ],
)
def test_requires_session(app, method, url, body):
    with TestClient(app) as client:
        response = getattr(client, method)(url, **({"json": body} if body else {}))
    assert response.status_code == 401


def test_onboarding_cards_and_exclusions(client):
    cards = client.get("/api/onboarding").json()
    assert {c["movie_id"] for c in cards} == {1, 2, 3}
    first = next(c for c in cards if c["movie_id"] == 1)
    assert first == {
        "movie_id": 1,
        "title": "A",
        "year": 1999,
        "poster_path": "/a.jpg",
        "genres": ["Drama"],
    }
    client.post("/api/ratings", json={"movie_id": 1, "value": 1})
    client.post("/api/seen", json={"movie_id": 2, "type": "not_interested"})
    assert [c["movie_id"] for c in client.get("/api/onboarding").json()] == [3]
    assert len(client.get("/api/onboarding?limit=1").json()) == 1
    assert client.get("/api/onboarding?limit=0").status_code == 422


def test_rating_updates_count_and_invalidates_cache(app, client):
    store = app.state.matrix_store
    before = store.get()
    response = client.post("/api/ratings", json={"movie_id": 1, "value": 1})
    assert response.json() == {"ok": True, "rated_count": 1}
    assert store.get() is not before
    response = client.post("/api/ratings", json={"movie_id": 1, "value": -1})
    assert response.json() == {"ok": True, "rated_count": 1}
    response = client.post("/api/ratings", json={"movie_id": 2, "value": 1})
    assert response.json()["rated_count"] == 2


@pytest.mark.parametrize("value", [0, 2, "x", True, None])
def test_rating_invalid_value_422(client, value):
    assert client.post("/api/ratings", json={"movie_id": 1, "value": value}).status_code == 422


def test_rating_unknown_movie_404(client):
    assert client.post("/api/ratings", json={"movie_id": 99, "value": 1}).status_code == 404


def test_rating_event_only_with_session_id(app, client):
    client.post("/api/ratings", json={"movie_id": 1, "value": 1})
    client.post("/api/ratings", json={"movie_id": 1, "value": 1, "session_id": None})
    assert _events(app) == []
    client.post("/api/ratings", json={"movie_id": 1, "value": 1, "session_id": "s"})
    client.post("/api/ratings", json={"movie_id": 2, "value": -1, "session_id": "s"})
    assert _events(app) == [("like", 1, "s"), ("dislike", 2, "s")]


def test_seen_marks_and_events(app, client):
    response = client.post("/api/seen", json={"movie_id": 1, "type": "watched", "session_id": "s"})
    assert response.json() == {"ok": True, "rated_count": 0}
    client.post("/api/seen", json={"movie_id": 2, "type": "not_interested"})
    client.post("/api/seen", json={"movie_id": 3, "type": "not_seen", "session_id": "s"})
    assert _events(app) == [("watched", 1, "s")]
    with app.state.session_factory() as session:
        marks = {m.movie_id: m.type for m in session.scalars(select(SeenMark))}
    assert marks == {1: "watched", 2: "not_interested", 3: "not_seen"}


def test_seen_invalid_type_422_and_unknown_movie_404(client):
    assert client.post("/api/seen", json={"movie_id": 1, "type": "x"}).status_code == 422
    assert client.post("/api/seen", json={"movie_id": 99, "type": "watched"}).status_code == 404
