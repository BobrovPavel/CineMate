from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.api.app import create_app
from cinemate.api.deps import get_db_session, get_matrix_store
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Base, Movie


@pytest.fixture
def app():
    return create_app("sqlite:///:memory:")


def test_health(app):
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_tables_created_on_empty_database(app):
    assert set(Base.metadata.tables) <= set(_table_names(app))


def _table_names(app):
    from sqlalchemy import inspect

    return inspect(app.state.engine).get_table_names()


def test_session_commits_on_success(app):
    @app.post("/_movie")
    def add(session: Annotated[Session, Depends(get_db_session)]):
        session.add(Movie(title="A"))
        return {}

    with TestClient(app) as client:
        assert client.post("/_movie").status_code == 200
    with app.state.session_factory() as session:
        assert session.scalars(select(Movie.title)).all() == ["A"]


def test_session_rolls_back_on_exception(app):
    @app.post("/_boom")
    def boom(session: Annotated[Session, Depends(get_db_session)]):
        session.add(Movie(title="A"))
        session.flush()
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/_boom").status_code == 500
    with app.state.session_factory() as session:
        assert session.scalars(select(Movie.title)).all() == []


def test_single_matrix_store_per_app(app):
    seen = []

    @app.get("/_store")
    def store(store: Annotated[MatrixStore, Depends(get_matrix_store)]):
        seen.append(store)
        return {}

    with TestClient(app) as client:
        client.get("/_store")
        client.get("/_store")
    assert seen[0] is seen[1] is app.state.matrix_store


def test_create_app_uses_env_database_url(monkeypatch, tmp_path):
    db = tmp_path / "x.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    app = create_app()
    assert str(app.state.engine.url.database) == str(db)


def _user_count(app):
    from cinemate.db.models import User

    with app.state.session_factory() as session:
        return len(session.scalars(select(User)).all())


def test_session_creates_user_and_cookie(app):
    with TestClient(app) as client:
        response = client.post("/api/session")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user_id"}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("cinemate_session=")
    token = cookie.split(";")[0].split("=", 1)[1]
    assert token not in response.text
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "max-age=31536000" in lowered
    assert "secure" not in lowered.replace("samesite", "")
    assert _user_count(app) == 1


def test_session_cookie_secure_flag():
    app = create_app("sqlite:///:memory:", cookie_secure=True)
    with TestClient(app) as client:
        response = client.post("/api/session")
    assert "; secure" in response.headers["set-cookie"].lower()


def test_session_reuses_existing_user(app):
    with TestClient(app) as client:
        first = client.post("/api/session").json()
        second = client.post("/api/session")
    assert second.json() == first
    assert "set-cookie" not in second.headers
    assert _user_count(app) == 1


def test_session_with_unknown_cookie_creates_new_user(app):
    with TestClient(app) as client:
        client.cookies.set("cinemate_session", "bogus")
        response = client.post("/api/session")
    assert response.status_code == 200
    assert "set-cookie" in response.headers
    assert _user_count(app) == 1


def test_profile_requires_session(app):
    with TestClient(app) as client:
        assert client.get("/api/profile").status_code == 401
        client.cookies.set("cinemate_session", "someone-else")
        assert client.get("/api/profile").status_code == 401


def test_profile_empty_then_with_ratings_newest_first(app):
    from cinemate.services.users import get_user_by_token, set_rating

    with TestClient(app) as client:
        client.post("/api/session")
        assert client.get("/api/profile").json() == []
        token = client.cookies.get("cinemate_session")
        with app.state.session_factory() as session:
            session.add_all(
                [
                    Movie(id=1, title="A", year=1999, poster_path="/a.jpg"),
                    Movie(id=2, title="B"),
                ]
            )
            session.flush()
            user = get_user_by_token(session, token)
            set_rating(session, user, 1, 1)
            set_rating(session, user, 2, -1)
            session.commit()
        response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json() == [
        {"movie_id": 2, "title": "B", "year": None, "poster_path": None, "value": -1},
        {"movie_id": 1, "title": "A", "year": 1999, "poster_path": "/a.jpg", "value": 1},
    ]
