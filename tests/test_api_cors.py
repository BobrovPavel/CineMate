import pytest
from fastapi.testclient import TestClient

from cinemate.api.app import create_app

ALLOWED = "http://localhost:3000"


def _preflight(client, origin):
    return client.options(
        "/api/ratings",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )


def test_preflight_allowed_origin(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with TestClient(create_app("sqlite:///:memory:")) as client:
        response = _preflight(client, ALLOWED)
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_foreign_origin_gets_no_cors_headers(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with TestClient(create_app("sqlite:///:memory:")) as client:
        response = _preflight(client, "http://evil.example")
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_origins_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example, http://b.example")
    with TestClient(create_app("sqlite:///:memory:")) as client:
        assert _preflight(client, "http://b.example").headers["access-control-allow-origin"] == (
            "http://b.example"
        )
        assert "access-control-allow-origin" not in _preflight(client, ALLOWED).headers


def test_argument_overrides_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example")
    app = create_app("sqlite:///:memory:", cors_origins=["http://c.example"])
    with TestClient(app) as client:
        assert "access-control-allow-origin" in _preflight(client, "http://c.example").headers
        assert "access-control-allow-origin" not in _preflight(client, "http://a.example").headers


def test_wildcard_rejected_in_argument_and_env(monkeypatch):
    with pytest.raises(ValueError, match="'\\*'"):
        create_app("sqlite:///:memory:", cors_origins=["*"])
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example,*")
    with pytest.raises(ValueError, match="'\\*'"):
        create_app("sqlite:///:memory:")


def test_no_origin_header_unchanged(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with TestClient(create_app("sqlite:///:memory:")) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
