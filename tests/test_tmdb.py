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
            "title": "История игрушек",
        }
    )
    assert client.fetch_movie(862) == TmdbMovie(
        "Описание", "/p.jpg", 81, "Toy Story", "История игрушек"
    )
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


def test_fetch_movie_empty_title_is_none():
    client, _ = _client(payload={"title": ""})
    assert client.fetch_movie(1).title is None


# --- search / fetch_details / rate limiting ---

SEARCH_FIXTURE = {
    "page": 1,
    "results": [
        {
            "media_type": "movie",
            "id": 10,
            "title": "Leviathan",
            "original_title": "Левиафан",
            "release_date": "2014-06-05",
            "poster_path": "/l.jpg",
        },
        {
            "media_type": "tv",
            "id": 1399,
            "name": "Game of Thrones",
            "original_name": "Game of Thrones",
            "first_air_date": "2011-04-17",
            "poster_path": None,
        },
        {"media_type": "person", "id": 5, "name": "Someone", "profile_path": "/x.jpg"},
        {"media_type": "movie", "id": 11, "title": "No date", "release_date": ""},
    ],
}


def test_search_parses_movies_and_tv_and_drops_people():
    from cinemate.tmdb import TmdbSearchItem

    client, calls = _client(payload=SEARCH_FIXTURE)
    items = client.search("leviathan", "ru-RU")
    assert items == [
        TmdbSearchItem("movie", 10, "Leviathan", "Левиафан", 2014, "/l.jpg"),
        TmdbSearchItem("tv", 1399, "Game of Thrones", "Game of Thrones", 2011, None),
        TmdbSearchItem("movie", 11, "No date", None, None, None),
    ]
    assert "/search/multi" in calls[0]
    assert "include_adult=false" in calls[0]
    assert "language=ru-RU" in calls[0]
    assert "page=1" in calls[0]


def test_search_encodes_query_and_handles_empty():
    client, calls = _client(payload={"results": []})
    assert client.search("a&b c", "en-US", page=3) == []
    assert "query=a%26b+c" in calls[0]
    assert "page=3" in calls[0]


MOVIE_FIXTURE = {
    "id": 10,
    "title": "Leviathan",
    "original_title": "Левиафан",
    "release_date": "2014-06-05",
    "poster_path": "/l.jpg",
    "runtime": 140,
    "overview": "English overview",
    "genres": [{"id": 18, "name": "Drama"}],
    "external_ids": {"imdb_id": "tt2802154"},
    "translations": {
        "translations": [
            {"iso_639_1": "de", "data": {"title": "Leviathan", "overview": "Deutsch"}},
            {
                "iso_639_1": "ru",
                "iso_3166_1": "RU",
                "data": {"title": "Левиафан", "overview": "Русское описание", "runtime": 140},
            },
        ]
    },
}


def test_fetch_details_movie_with_translation():
    client, calls = _client(payload=MOVIE_FIXTURE)
    details = client.fetch_details("movie", 10)
    assert (details.title, details.original_title, details.year) == ("Leviathan", "Левиафан", 2014)
    assert (details.runtime, details.genres, details.imdb_id) == (140, ["Drama"], "tt2802154")
    assert (details.title_ru, details.overview_ru) == ("Левиафан", "Русское описание")
    assert details.overview == "English overview"
    assert "/movie/10" in calls[0]
    assert "language=en-US" in calls[0]
    assert "append_to_response=external_ids%2Ctranslations" in calls[0]


def test_fetch_details_without_russian_translation():
    payload = {**MOVIE_FIXTURE, "translations": {"translations": []}}
    client, _ = _client(payload=payload)
    details = client.fetch_details("movie", 10)
    assert details.title_ru is None
    assert details.overview_ru is None


def test_fetch_details_empty_russian_fields_are_none():
    payload = {
        **MOVIE_FIXTURE,
        "translations": {
            "translations": [{"iso_639_1": "ru", "data": {"title": "", "overview": ""}}]
        },
    }
    client, _ = _client(payload=payload)
    details = client.fetch_details("movie", 10)
    assert (details.title_ru, details.overview_ru) == (None, None)


def test_fetch_details_tv():
    payload = {
        "id": 1399,
        "name": "Game of Thrones",
        "original_name": "Game of Thrones",
        "first_air_date": "2011-04-17",
        "poster_path": "/g.jpg",
        "episode_run_time": [60],
        "genres": [],
        "external_ids": {"imdb_id": "tt0944947"},
        "translations": {
            "translations": [
                {"iso_639_1": "ru", "data": {"name": "Игра престолов", "overview": "О"}}
            ]
        },
    }
    client, calls = _client(payload=payload)
    details = client.fetch_details("tv", 1399)
    assert (details.tmdb_type, details.title, details.year, details.runtime) == (
        "tv",
        "Game of Thrones",
        2011,
        60,
    )
    assert (details.title_ru, details.imdb_id) == ("Игра престолов", "tt0944947")
    assert "/tv/1399" in calls[0]


def test_fetch_details_unknown_and_invalid_type():
    client, _ = _client(status=404)
    assert client.fetch_details("movie", 1) is None
    with pytest.raises(ValueError):
        client.fetch_details("person", 1)


def _sequence(responses):
    calls = []
    remaining = list(responses)

    def http_get(url):
        calls.append(url)
        item = remaining.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return http_get, calls


def test_429_pauses_for_retry_after_and_retries_once():
    from cinemate.tmdb import TmdbRateLimited

    http_get, calls = _sequence([TmdbRateLimited(3.0), (200, b'{"results": []}')])
    sleeps = []
    client = TmdbClient(KEY, http_get=http_get, clock=lambda: 0.0, sleep=sleeps.append)
    assert client.search("matrix", "en-US") == []
    assert len(calls) == 2
    assert 3.0 in sleeps


def test_429_status_retries_once_then_fails():
    from cinemate.tmdb import TmdbRateLimited

    http_get, calls = _sequence([(429, b""), (429, b"")])
    client = TmdbClient(KEY, http_get=http_get, clock=lambda: 0.0, sleep=lambda s: None)
    with pytest.raises(TmdbRateLimited) as exc:
        client.search("matrix", "en-US")
    assert len(calls) == 2
    assert KEY not in str(exc.value)


def test_requests_are_limited_to_20_per_second():
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    client = TmdbClient(
        KEY, http_get=lambda url: (200, b'{"results": []}'), clock=lambda: now[0], sleep=sleep
    )
    for _ in range(21):
        client.search("matrix", "en-US")
    assert now[0] == pytest.approx(1.0)


def test_find_by_imdb_prefers_movie_then_tv():
    client, calls = _client(
        payload={
            "movie_results": [],
            "tv_results": [{"id": 1399, "name": "GoT", "first_air_date": "2011-04-17"}],
        }
    )
    item = client.find_by_imdb("tt0944947")
    assert (item.tmdb_type, item.tmdb_id, item.year) == ("tv", 1399, 2011)
    assert "/find/tt0944947" in calls[0]
    assert "external_source=imdb_id" in calls[0]


def test_find_by_imdb_none_when_empty():
    client, _ = _client(payload={"movie_results": [], "tv_results": []})
    assert client.find_by_imdb("tt1") is None
