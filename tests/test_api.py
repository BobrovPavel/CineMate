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
