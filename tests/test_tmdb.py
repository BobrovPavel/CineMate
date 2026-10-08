import json

import pytest

from cinemate.tmdb import TmdbClient, TmdbError, TmdbMovie

KEY = "secret-key-123"


def _client(status=200, payload=None, raises=None):
    calls = []

    def http_get(url):
        calls.append(url)
        if raises is not None:
            raise raises
        return status, json.dumps(payload or {}).encode()

    return TmdbClient(KEY, http_get=http_get), calls


def test_fetch_movie_success():
    client, calls = _client(
        payload={
            "overview": "Описание",
            "poster_path": "/p.jpg",
            "runtime": 81,
            "original_title": "Toy Story",
        }
    )
    assert client.fetch_movie(862) == TmdbMovie("Описание", "/p.jpg", 81, "Toy Story")
    assert "/movie/862" in calls[0]
    assert "language=ru-RU" in calls[0]


def test_fetch_movie_404_returns_none():
    client, _ = _client(status=404)
    assert client.fetch_movie(1) is None


def test_fetch_movie_http_error():
    client, _ = _client(status=500)
    with pytest.raises(TmdbError) as exc:
        client.fetch_movie(1)
    assert KEY not in str(exc.value)


def test_transport_error_does_not_leak_key():
    client, _ = _client(raises=OSError(f"failed https://x/?api_key={KEY}"))
    with pytest.raises(TmdbError) as exc:
        client.fetch_movie(1)
    assert KEY not in str(exc.value)
    assert KEY not in repr(exc.value.__cause__)


def test_invalid_json():
    client = TmdbClient(KEY, http_get=lambda url: (200, b"not json"))
    with pytest.raises(TmdbError):
        client.fetch_movie(1)


def test_repr_hides_key():
    assert KEY not in repr(TmdbClient(KEY, http_get=lambda url: (404, b"")))


def test_empty_key_rejected():
    with pytest.raises(ValueError):
        TmdbClient("")
