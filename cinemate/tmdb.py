"""Minimal TMDB client: fetches movie metadata in Russian."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

API_URL = "https://api.themoviedb.org/3/movie/{tmdb_id}"
TIMEOUT = 10.0

HttpGet = Callable[[str], tuple[int, bytes]]


class TmdbError(Exception):
    """A TMDB request failed. Messages never contain the API key or the request URL."""


@dataclass(frozen=True)
class TmdbMovie:
    overview: str | None
    poster_path: str | None
    runtime: int | None
    original_title: str | None


def urllib_get(url: str) -> tuple[int, bytes]:
    """Default transport: return ``(status, body)``; HTTP error statuses are returned."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # The original exception may mention the URL (and so the key); keep only its type.
        raise TmdbError(f"TMDB request failed: {type(exc).__name__}") from None


class TmdbClient:
    def __init__(self, api_key: str, http_get: HttpGet = urllib_get) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._api_key = api_key
        self._http_get = http_get

    def __repr__(self) -> str:
        return "TmdbClient(api_key='***')"

    def fetch_movie(self, tmdb_id: int) -> TmdbMovie | None:
        """Return metadata for ``tmdb_id``, ``None`` if TMDB does not know it."""
        url = API_URL.format(tmdb_id=int(tmdb_id)) + f"?api_key={self._api_key}&language=ru-RU"
        try:
            status, body = self._http_get(url)
        except TmdbError:
            raise
        except Exception as exc:
            raise TmdbError(f"TMDB request failed: {type(exc).__name__}") from None
        if status == 404:
            return None
        if status != 200:
            raise TmdbError(f"TMDB returned HTTP {status}")
        try:
            data = json.loads(body)
        except ValueError:
            raise TmdbError("TMDB returned invalid JSON") from None
        if not isinstance(data, dict):
            raise TmdbError("TMDB returned an unexpected response")
        return TmdbMovie(
            overview=data.get("overview") or None,
            poster_path=data.get("poster_path") or None,
            runtime=data.get("runtime") or None,
            original_title=data.get("original_title") or None,
        )
