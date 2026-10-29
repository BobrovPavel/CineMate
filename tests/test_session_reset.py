import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemate.api.app import create_app
from cinemate.db.models import Movie, Rating, User


@pytest.fixture
def app():
    return create_app("sqlite:///:memory:")


def _users(app):
    with app.state.session_factory() as session:
        return list(session.scalars(select(User).order_by(User.id)))


def _add_movie(app):
    with app.state.session_factory() as session:
        movie = Movie(title="A")
        session.add(movie)
        session.commit()
        return movie.id


def test_reset_creates_new_user_with_new_cookie_and_keeps_old(app):
    movie_id = _add_movie(app)
    with TestClient(app) as client:
        first = client.post("/api/session", headers={"Accept-Language": "ru"}).json()
        old_token = client.cookies.get("cinemate_session")
        assert (
            client.post("/api/ratings", json={"movie_id": movie_id, "value": 1}).status_code == 200
        )
        response = client.post("/api/session/reset", headers={"Accept-Language": "en"})
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"user_id", "pool"}
        assert body["user_id"] != first["user_id"]
        assert (first["pool"], body["pool"]) == ("ru", "world")
        lowered = response.headers["set-cookie"].lower()
        assert lowered.startswith("cinemate_session=")
        assert "httponly" in lowered and "samesite=lax" in lowered
        assert "max-age=31536000" in lowered
        assert client.cookies.get("cinemate_session") != old_token
        assert client.get("/api/profile").json() == []
    users = _users(app)
    assert [u.id for u in users] == [first["user_id"], body["user_id"]]
    assert users[0].session_token == old_token
    with app.state.session_factory() as session:
        ratings = session.scalars(select(Rating)).all()
    assert [(r.user_id, r.movie_id, r.value) for r in ratings] == [(first["user_id"], movie_id, 1)]


def test_reset_pool_by_language_cookie(app):
    with TestClient(app) as client:
        client.post("/api/session")
        client.cookies.set("cinemate_lang", "ru")
        assert client.post("/api/session/reset").json()["pool"] == "ru"
        client.cookies.set("cinemate_lang", "en")
        assert (
            client.post("/api/session/reset", headers={"Accept-Language": "ru"}).json()["pool"]
            == "world"
        )


def test_reset_without_session_cookie_works(app):
    with TestClient(app) as client:
        response = client.post("/api/session/reset", headers={"Accept-Language": "ru"})
    assert response.status_code == 200
    assert response.json()["pool"] == "ru"
    assert "cinemate_session=" in response.headers["set-cookie"]
    assert len(_users(app)) == 1


def test_me_requires_session(app):
    with TestClient(app) as client:
        assert client.get("/api/me").status_code == 401


def test_me_returns_pool_and_rated_count(app):
    movie_id = _add_movie(app)
    with TestClient(app) as client:
        created = client.post("/api/session", headers={"Accept-Language": "ru"}).json()
        assert client.get("/api/me").json() == {
            "user_id": created["user_id"],
            "pool": "ru",
            "rated_count": 0,
        }
        client.post("/api/ratings", json={"movie_id": movie_id, "value": -1})
        assert client.get("/api/me").json()["rated_count"] == 1
