"""Minimal TMDB client: movie metadata in Russian, multi-search and details by TMDB pair."""

import contextlib
import http.client
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date, timedelta

API_BASE = "https://api.themoviedb.org/3"
TIMEOUT = 10.0
MAX_REQUESTS_PER_SECOND = 20
DEFAULT_WORKERS = 8
MAX_WORKERS = 16
DEFAULT_RPS = MAX_REQUESTS_PER_SECOND
MAX_RPS = 35
BULK_CONSECUTIVE_429 = 5  # bulk commands stop after this many 429 in a row
MAX_CONSECUTIVE_429 = 2  # API default: one retry after a 429, the second one in a row fails
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
        super().__init__("TMDB rate limit exceeded (HTTP 429); progress is saved, rerun later")
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


ConnectionFactory = Callable[[str, float], http.client.HTTPSConnection]


def _https_connection(host: str, timeout: float) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(host, timeout=timeout)


class PersistentTransport:
    """Default TMDB transport: one kept-alive HTTPS connection per thread and host.

    A broken connection (reset, timeout, closed by the server) is replaced and the request is
    repeated once on the new one. Same contract as ``urllib_get``: ``(status, body)``, a 429 raises
    ``TmdbRateLimited``, other failures ``TmdbError`` without the URL (it holds the API key).
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory = _https_connection,
        timeout: float = TIMEOUT,
    ) -> None:
        self._factory = connection_factory
        self._timeout = timeout
        self._local = threading.local()

    def _connection(self, host: str) -> http.client.HTTPSConnection:
        connections = self._local.__dict__.setdefault("connections", {})
        if host not in connections:
            connections[host] = self._factory(host, self._timeout)
        return connections[host]

    def _drop(self, host: str) -> None:
        connection = self._local.__dict__.setdefault("connections", {}).pop(host, None)
        if connection is not None:
            with contextlib.suppress(Exception):  # already broken, nothing to save
                connection.close()

    def __call__(self, url: str) -> tuple[int, bytes]:
        parts = urllib.parse.urlsplit(url)
        target = f"{parts.path}?{parts.query}" if parts.query else parts.path
        failure: Exception | None = None
        for _ in range(2):
            try:
                connection = self._connection(parts.netloc)
                connection.request("GET", target)
                response = connection.getresponse()
                body = response.read()
            except (http.client.HTTPException, OSError) as exc:
                self._drop(parts.netloc)
                failure = exc
                continue
            if response.will_close:
                self._drop(parts.netloc)
            if response.status == 429:
                raise TmdbRateLimited(_parse_retry_after(response.getheader("Retry-After")))
            return response.status, body
        # The original exception may mention the URL (and so the key); keep only its type.
        raise TmdbError(f"TMDB request failed: {type(failure).__name__}") from None


class TmdbClient:
    """Thin TMDB v3 client.

    Requests are spaced to at most ``requests_per_second`` per client (and so per process, as the
    app keeps one), whatever the number of threads. A 429 answer shifts the shared limiter by
    ``Retry-After``, so every thread pauses, and the request is repeated; the
    ``max_consecutive_429``-th 429 in a row (counted over all threads) raises ``TmdbRateLimited``.
    """

    def __init__(
        self,
        api_key: str,
        http_get: HttpGet | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        requests_per_second: float = MAX_REQUESTS_PER_SECOND,
        max_consecutive_429: int = MAX_CONSECUTIVE_429,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        if not requests_per_second > 0:
            raise ValueError("requests_per_second must be > 0")
        if max_consecutive_429 < 1:
            raise ValueError("max_consecutive_429 must be >= 1")
        self._api_key = api_key
        self._http_get = http_get or PersistentTransport()
        self._clock = clock
        self._sleep = sleep
        self._interval = 1.0 / requests_per_second
        self._max_429 = max_consecutive_429
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._streak_429 = 0

    def __repr__(self) -> str:
        return "TmdbClient(api_key='***')"

    def _throttle(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._interval
        if wait > 0:
            self._sleep(wait)

    def _rate_limited(self, retry_after: float) -> None:
        """Count a 429 and pause every thread for ``retry_after``; raise after too many."""
        with self._lock:
            self._streak_429 += 1
            if self._streak_429 >= self._max_429:
                self._streak_429 = 0
                raise TmdbRateLimited(retry_after)
            self._next_slot = max(self._next_slot, self._clock() + retry_after)

    def _succeeded(self) -> None:
        with self._lock:
            self._streak_429 = 0

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
        while True:
            try:
                status, body = self._send(url)
            except TmdbRateLimited as exc:
                self._rate_limited(exc.retry_after)
                continue
            if status != 429:
                break
            self._rate_limited(DEFAULT_RETRY_AFTER)
        self._succeeded()
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


def fetch_many(
    client: TmdbClient, items: Iterable[tuple[str, int]], workers: int = DEFAULT_WORKERS
) -> Iterator[tuple[tuple[str, int], TmdbDetails | None]]:
    """``client.fetch_details`` for each ``(tmdb_type, tmdb_id)``, ``workers`` at a time.

    Yields ``((tmdb_type, tmdb_id), details)`` in completion order, in the calling thread (so the
    caller may use a database session there); ``details`` is ``None`` for a 404. At most
    ``2 * workers`` requests are submitted ahead. When a request fails (any exception, including
    ``KeyboardInterrupt`` in the caller or a worker) nothing new is sent, requests already running
    finish and their results are yielded, then the first error is raised. ``workers == 1`` runs
    in the calling thread, one request after another.
    """
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if workers == 1:
        for pair in items:
            yield pair, client.fetch_details(*pair)
        return
    iterator = iter(items)
    pending: dict[Future, tuple[str, int]] = {}
    error: BaseException | None = None
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tmdb")
    try:
        while True:
            while error is None and len(pending) < 2 * workers:
                pair = next(iterator, None)
                if pair is None:
                    break
                pending[executor.submit(client.fetch_details, *pair)] = pair
            if not pending:
                break
            try:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
            except BaseException as exc:  # noqa: BLE001 - Ctrl+C while waiting
                error, done = error or exc, set()
            for future in done:
                pair = pending.pop(future)
                if future.cancelled():
                    continue
                try:
                    details = future.result()
                except BaseException as exc:  # noqa: BLE001 - a worker may raise anything
                    error = error or exc
                else:
                    yield pair, details
            if error is not None:
                for future in list(pending):
                    if future.cancel():
                        del pending[future]
        if error is not None:
            raise error
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
