"""Kinopoisk -> TMDB/IMDb mapping from Wikidata (CC0): fetch via SPARQL, save and load as CSV."""

import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "CineMate/0.1 (https://github.com/BobrovPavel/CineMate; non-commercial research)"
DEFAULT_PATH = Path("data/wikidata_kinopoisk.csv")
PAGE_SIZE = 20000
PAUSE = 2.0
TIMEOUT = 90.0
MAX_ATTEMPTS = 4
DEFAULT_RETRY_AFTER = 5.0
MAX_RETRY_AFTER = 60.0
FIELDS = ("kp_id", "tmdb_type", "tmdb_id", "imdb_id")

_QUERY = """\
SELECT ?kp ?tmdbMovie ?tmdbTv ?imdb WHERE {{
  {{ SELECT ?item ?kp WHERE {{ ?item wdt:P2603 ?kp }} ORDER BY ?kp LIMIT {limit} OFFSET {offset} }}
  OPTIONAL {{ ?item wdt:P4947 ?tmdbMovie }}
  OPTIONAL {{ ?item wdt:P4983 ?tmdbTv }}
  OPTIONAL {{ ?item wdt:P345 ?imdb }}
}}"""

HttpGet = Callable[[str, dict[str, str]], tuple[int, bytes, float | None]]


class WikidataError(Exception):
    """A Wikidata request failed or returned something unexpected."""


@dataclass(frozen=True)
class WikidataEntry:
    tmdb_type: str | None
    tmdb_id: int | None
    imdb_id: str | None


@dataclass(frozen=True)
class FetchResult:
    entries: dict[int, WikidataEntry]
    dropped: int  # kp ids left out because their TMDB pair is ambiguous


def urllib_get(url: str, headers: dict[str, str]) -> tuple[int, bytes, float | None]:
    """Default transport: ``(status, body, Retry-After seconds)``; HTTP errors are returned."""
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return response.status, response.read(), None
    except urllib.error.HTTPError as exc:
        try:
            retry = float(exc.headers.get("Retry-After"))
        except (TypeError, ValueError):
            retry = None
        return exc.code, b"", retry
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WikidataError(f"Wikidata request failed: {type(exc).__name__}") from None


def _digits(binding: dict, name: str) -> int | None:
    value = (binding.get(name) or {}).get("value")
    return int(value) if isinstance(value, str) and value.isdigit() else None


def parse_bindings(
    bindings: Iterable[dict],
) -> tuple[dict[int, set[tuple[str, int]]], dict[int, set[str]]]:
    """Per kp id: the TMDB pairs and IMDb ids seen in SPARQL result bindings."""
    pairs: dict[int, set[tuple[str, int]]] = defaultdict(set)
    imdbs: dict[int, set[str]] = defaultdict(set)
    for b in bindings:
        kp = _digits(b, "kp")
        if kp is None:
            continue
        pairs[kp]  # noqa: B018 - register the kp id even without a pair
        imdbs[kp]  # noqa: B018
        for name, kind in (("tmdbMovie", "movie"), ("tmdbTv", "tv")):
            tmdb_id = _digits(b, name)
            if tmdb_id is not None:
                pairs[kp].add((kind, tmdb_id))
        imdb = (b.get("imdb") or {}).get("value")
        if isinstance(imdb, str) and imdb.startswith("tt"):
            imdbs[kp].add(imdb)
    return pairs, imdbs


def build_entries(
    pairs: dict[int, set[tuple[str, int]]], imdbs: dict[int, set[str]]
) -> FetchResult:
    """Drop kp ids with several TMDB pairs and pairs shared by several kp ids.

    An ambiguous IMDb id (several per kp id) is only left out of the entry. Rows with neither a
    pair nor an IMDb id are not kept.
    """
    owners: dict[tuple[str, int], int] = defaultdict(int)
    for options in pairs.values():
        if len(options) == 1:
            owners[next(iter(options))] += 1
    entries: dict[int, WikidataEntry] = {}
    dropped = 0
    for kp in sorted(pairs):
        options = pairs[kp]
        pair = next(iter(options)) if len(options) == 1 else None
        if len(options) > 1 or (pair is not None and owners[pair] > 1):
            dropped += 1
            continue
        imdb = next(iter(imdbs[kp])) if len(imdbs[kp]) == 1 else None
        if pair is None and imdb is None:
            continue
        entries[kp] = WikidataEntry(pair[0] if pair else None, pair[1] if pair else None, imdb)
    return FetchResult(entries, dropped)


def fetch_mapping(
    http_get: HttpGet = urllib_get,
    sleep: Callable[[float], None] = time.sleep,
    page_size: int = PAGE_SIZE,
    pause: float = PAUSE,
    progress: Callable[[int], None] | None = None,
) -> FetchResult:
    """Download every Wikidata item with a Kinopoisk id, page by page (sorted by kp id)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    all_bindings: list[dict] = []
    offset = 0
    while True:
        query = _QUERY.format(limit=page_size, offset=offset)
        url = f"{SPARQL_URL}?{urllib.parse.urlencode({'query': query, 'format': 'json'})}"
        bindings = _request(url, headers, http_get, sleep)
        all_bindings.extend(bindings)
        kp_count = len({b.get("kp", {}).get("value") for b in bindings})
        offset += page_size
        if progress is not None:
            progress(len(all_bindings))
        if kp_count < page_size:
            break
        sleep(pause)
    return build_entries(*parse_bindings(all_bindings))


def _request(url: str, headers: dict[str, str], http_get: HttpGet, sleep) -> list[dict]:
    for attempt in range(MAX_ATTEMPTS):
        status, body, retry_after = http_get(url, headers)
        if status == 200:
            break
        if (status == 429 or status >= 500) and attempt < MAX_ATTEMPTS - 1:
            pause = DEFAULT_RETRY_AFTER if retry_after is None else retry_after
            sleep(min(max(pause, 0.0), MAX_RETRY_AFTER) * (1 if status == 429 else attempt + 1))
            continue
        raise WikidataError(f"Wikidata returned HTTP {status}")
    try:
        bindings = json.loads(body)["results"]["bindings"]
    except (ValueError, KeyError, TypeError):
        raise WikidataError("Wikidata returned an unexpected response") from None
    if not isinstance(bindings, list):
        raise WikidataError("Wikidata returned an unexpected response")
    return [b for b in bindings if isinstance(b, dict)]


def save_mapping(path: Path | str, entries: dict[int, WikidataEntry]) -> None:
    """Write the mapping as CSV (``kp_id,tmdb_type,tmdb_id,imdb_id``), replacing the file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        for kp in sorted(entries):
            e = entries[kp]
            writer.writerow([kp, e.tmdb_type or "", e.tmdb_id or "", e.imdb_id or ""])
    os.replace(tmp, path)


def load_mapping(path: Path | str) -> dict[int, WikidataEntry]:
    """Read a CSV written by ``save_mapping``; malformed rows are skipped."""
    entries: dict[int, WikidataEntry] = {}
    with Path(path).open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            kp = (row.get("kp_id") or "").strip()
            tmdb_id = (row.get("tmdb_id") or "").strip()
            tmdb_type = (row.get("tmdb_type") or "").strip()
            has_pair = tmdb_id.isdigit() and tmdb_type in ("movie", "tv")
            imdb = (row.get("imdb_id") or "").strip() or None
            if not kp.isdigit() or not (has_pair or imdb):
                continue
            entries[int(kp)] = WikidataEntry(
                tmdb_type if has_pair else None, int(tmdb_id) if has_pair else None, imdb
            )
    return entries
