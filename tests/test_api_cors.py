import pytest
from fastapi.testclient import TestClient

from cinemate.api.app import create_app

ALLOWED = "http://localhost:3000"


def _preflight(client, origin):
    return client.options(
        "/api/ratings",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_preflight_allowed_origin(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with TestClient(create_app("sqlite:///:memory:")) as client:
        response = _preflight(client, ALLOWED)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["access-control-allow-credentials"] == "true"


def test_foreign_origin_gets_no_cors_headers(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with TestClient(create_app("sqlite:///:memory:")) as client:
        response = _preflight(client, "http://evil.example")
        simple = client.get("/api/health", headers={"Origin": "http://evil.example"})
    # Starlette rejects the preflight and omits allow-origin (the browser blocks the request).
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-origin" not in simple.headers


def test_env_origins(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    with TestClient(create_app("sqlite:///:memory:")) as client:
        ok = _preflight(client, "https://b.example")
        default = _preflight(client, ALLOWED)
    assert ok.headers["access-control-allow-origin"] == "https://b.example"
    assert "access-control-allow-origin" not in default.headers


def test_argument_overrides_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    app = create_app("sqlite:///:memory:", cors_origins=["https://arg.example"])
    with TestClient(app) as client:
        arg = _preflight(client, "https://arg.example")
        env = _preflight(client, "https://a.example")
    assert arg.headers["access-control-allow-origin"] == "https://arg.example"
    assert "access-control-allow-origin" not in env.headers


def test_no_origin_header_unchanged(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with TestClient(create_app("sqlite:///:memory:")) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_wildcard_rejected_from_argument():
    with pytest.raises(ValueError, match="credentials"):
        create_app("sqlite:///:memory:", cors_origins=["*"])


def test_wildcard_rejected_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,*")
    with pytest.raises(ValueError, match="credentials"):
        create_app("sqlite:///:memory:")
