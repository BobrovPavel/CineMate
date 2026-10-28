"""Minimal TMDB client: movie metadata in Russian, multi-search and details by TMDB pair."""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta

API_BASE = "https://api.themoviedb.org/3"
TIMEOUT = 10.0
MAX_REQUESTS_PER_SECOND = 20
DEFAULT_RETRY_AFTER = 1.0
MAX_RETRY_AFTER = 10.0
MEDIA_TYPES = ("movie", "tv")
CHANGES_WINDOW_DAYS = 14  # TMDB rejects a /changes window longer than this

HttpGet = Callable[[str], tuple[int, bytes]]


class TmdbError(Exception):
    """A TMDB request failed. Messages never contain the API key or the request URL."""


class TmdbRateLimited(TmdbError):
    """TMDB answered 429; ``retry_after`` is the pause (seconds) it asked for."""

    def __init__(self, retry_after: float = DEFAULT_RETRY_AFTER) -> None:
        super().__init__("TMDB rate limit exceeded")
        self.retry_after = retry_after


@dataclass(frozen=True)
class TmdbSearchItem:
    tmdb_type: str
    tmdb_id: int
    title: str
    original_title: str | None
    year: int | None
    poster_path: str | None


@dataclass(frozen=True)
class TmdbDetails:
    tmdb_type: str
    tmdb_id: int
    title: str
    original_title: str | None
    year: int | None
    poster_path: str | None
    runtime: int | None
    genres: list[str] = field(default_factory=list)
    imdb_id: str | None = None
    title_ru: str | None = None
    overview_ru: str | None = None
    overview: str | None = None
    popularity: float | None = None


def _parse_retry_after(value: str | None) -> float:
    try:
        seconds = float(value) if value is not None else DEFAULT_RETRY_AFTER
    except ValueError:
        return DEFAULT_RETRY_AFTER
    return min(max(seconds, 0.0), MAX_RETRY_AFTER)


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _year(date: object) -> int | None:
    """Year of a ``YYYY-MM-DD`` date string, ``None`` if empty or malformed."""
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def date_windows(
    start: date, end: date, days: int = CHANGES_WINDOW_DAYS
) -> list[tuple[date, date]]:
    """Split ``start..end`` (inclusive) into consecutive windows of at most ``days`` days."""
    windows = []
    while start <= end:
        stop = min(start + timedelta(days=days - 1), end)
        windows.append((start, stop))
        start = stop + timedelta(days=1)
    return windows


def urllib_get(url: str) -> tuple[int, bytes]:
    """Default transport: return ``(status, body)``; HTTP error statuses are returned."""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise TmdbRateLimited(_parse_retry_after(exc.headers.get("Retry-After"))) from None
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # The original exception may mention the URL (and so the key); keep only its type.
        raise TmdbError(f"TMDB request failed: {type(exc).__name__}") from None


class TmdbClient:
    """Thin TMDB v3 client.

    Requests are spaced to at most ``MAX_REQUESTS_PER_SECOND`` per client (and so per process,
    as the app keeps one); a 429 answer pauses for ``Retry-After`` and retries once.
    """

    def __init__(
        self,
        api_key: str,
        http_get: HttpGet = urllib_get,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._api_key = api_key
        self._http_get = http_get
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def __repr__(self) -> str:
        return "TmdbClient(api_key='***')"

    def _throttle(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + 1.0 / MAX_REQUESTS_PER_SECOND
        if wait > 0:
            self._sleep(wait)

    def _send(self, url: str) -> tuple[int, bytes]:
        self._throttle()
        try:
            return self._http_get(url)
        except TmdbError:
            raise
        except Exception as exc:
            raise TmdbError(f"TMDB request failed: {type(exc).__name__}") from None

    def _get_json(self, path: str, **params: str | int | bool) -> dict | None:
        """GET ``path``; ``None`` on 404, ``TmdbError`` on anything but a JSON object."""
        query = urllib.parse.urlencode({"api_key": self._api_key, **params})
        url = f"{API_BASE}{path}?{query}"
        try:
            status, body = self._send(url)
        except TmdbRateLimited as exc:
            self._sleep(exc.retry_after)
            status, body = self._send(url)
        if status == 429:
            self._sleep(DEFAULT_RETRY_AFTER)
            status, body = self._send(url)
        if status == 404:
            return None
        if status == 429:
            raise TmdbRateLimited
        if status != 200:
            raise TmdbError(f"TMDB returned HTTP {status}")
        try:
            data = json.loads(body)
        except ValueError:
            raise TmdbError("TMDB returned invalid JSON") from None
        if not isinstance(data, dict):
            raise TmdbError("TMDB returned an unexpected response")
        return data

    def search(self, query: str, language: str, page: int = 1) -> list[TmdbSearchItem]:
        """Search movies and TV shows (``/search/multi``); people and adult titles are dropped."""
        data = self._get_json(
            "/search/multi", query=query, language=language, page=page, include_adult="false"
        )
        results = (data or {}).get("results")
        if not isinstance(results, list):
            return []
        items = []
        for raw in results:
            if not isinstance(raw, dict) or raw.get("media_type") not in MEDIA_TYPES:
                continue
            item = self._search_item(raw)
            if item is not None:
                items.append(item)
        return items

    def find_by_imdb(self, imdb_id: str) -> TmdbSearchItem | None:
        """The movie (else TV show) TMDB has for an IMDb id (``/find``), ``None`` if none."""
        data = self._get_json(
            f"/find/{urllib.parse.quote(imdb_id, safe='')}", external_source="imdb_id"
        )
        for media_type in MEDIA_TYPES:
            results = (data or {}).get(f"{media_type}_results")
            for raw in results if isinstance(results, list) else []:
                if isinstance(raw, dict):
                    item = self._search_item({**raw, "media_type": media_type})
                    if item is not None:
                        return item
        return None

    @staticmethod
    def _search_item(raw: dict) -> TmdbSearchItem | None:
        tmdb_id = _int_or_none(raw.get("id"))
        tv = raw["media_type"] == "tv"
        title = raw.get("name" if tv else "title")
        if tmdb_id is None or not title:
            return None
        return TmdbSearchItem(
            tmdb_type=raw["media_type"],
            tmdb_id=tmdb_id,
            title=title,
            original_title=raw.get("original_name" if tv else "original_title") or None,
            year=_year(raw.get("first_air_date" if tv else "release_date")),
            poster_path=raw.get("poster_path") or None,
        )

    def fetch_details(self, tmdb_type: str, tmdb_id: int) -> TmdbDetails | None:
        """English details plus the Russian translation of title and overview, if any.

        One request: ``/{movie|tv}/{id}?append_to_response=external_ids,translations``.
        ``None`` if TMDB does not know the pair.
        """
        if tmdb_type not in MEDIA_TYPES:
            raise ValueError(f"unknown tmdb_type: {tmdb_type!r}")
        data = self._get_json(
            f"/{tmdb_type}/{int(tmdb_id)}",
            language="en-US",
            append_to_response="external_ids,translations",
        )
        if data is None:
            return None
        tv = tmdb_type == "tv"
        title = data.get("name" if tv else "title")
        if not title:
            raise TmdbError("TMDB returned an unexpected response")
        external = data.get("external_ids")
        imdb_id = (external.get("imdb_id") if isinstance(external, dict) else None) or data.get(
            "imdb_id"
        )
        if tv:
            runtimes = data.get("episode_run_time")
            runtime = runtimes[0] if isinstance(runtimes, list) and runtimes else None
        else:
            runtime = data.get("runtime")
        genres = [
            g["name"] for g in data.get("genres") or [] if isinstance(g, dict) and g.get("name")
        ]
        title_ru, overview_ru = self._russian(data.get("translations"), tv)
        return TmdbDetails(
            tmdb_type=tmdb_type,
            tmdb_id=int(tmdb_id),
            title=title,
            original_title=data.get("original_name" if tv else "original_title") or None,
            year=_year(data.get("first_air_date" if tv else "release_date")),
            poster_path=data.get("poster_path") or None,
            runtime=_int_or_none(runtime) or None,
            genres=genres,
            imdb_id=imdb_id or None,
            title_ru=title_ru,
            overview_ru=overview_ru,
            overview=data.get("overview") or None,
            popularity=float(pop)
            if isinstance(pop := data.get("popularity"), int | float)
            else None,
        )

    def changes(self, tmdb_type: str, start: date, end: date) -> Iterator[int]:
        """Ids of records of ``tmdb_type`` created or changed in ``start..end`` (inclusive).

        Walks every page of ``/{movie|tv}/changes``; windows over 14 days are split into parts.
        ``adult`` records are skipped and an id seen twice (windows may overlap in time) is
        yielded once.
        """
        if tmdb_type not in MEDIA_TYPES:
            raise ValueError(f"unknown tmdb_type: {tmdb_type!r}")
        seen: set[int] = set()
        for window_start, window_end in date_windows(start, end):
            page, total_pages = 1, 1
            while page <= total_pages:
                data = self._get_json(
                    f"/{tmdb_type}/changes",
                    start_date=window_start.isoformat(),
                    end_date=window_end.isoformat(),
                    page=page,
                )
                results = (data or {}).get("results")
                if data is None or not isinstance(results, list):
                    raise TmdbError("TMDB returned an unexpected response")
                pages = _int_or_none(data.get("total_pages"))
                total_pages = pages if pages is not None else page
                page += 1
                for raw in results:
                    tmdb_id = _int_or_none(raw.get("id")) if isinstance(raw, dict) else None
                    if tmdb_id is None or raw.get("adult") is True or tmdb_id in seen:
                        continue
                    seen.add(tmdb_id)
                    yield tmdb_id

    @staticmethod
    def _russian(translations: object, tv: bool) -> tuple[str | None, str | None]:
        """Title and overview from the ``ru`` entry of ``translations``; ``None`` if empty."""
        entries = translations.get("translations") if isinstance(translations, dict) else None
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("iso_639_1") == "ru":
                data = entry.get("data")
                if not isinstance(data, dict):
                    return None, None
                return (data.get("name" if tv else "title") or None, data.get("overview") or None)
        return None, None
