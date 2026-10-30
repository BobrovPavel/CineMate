import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cinemate.cli import main
from cinemate.db.details import apply_extended, ensure_extended
from cinemate.db.enrich import enrich_movies
from cinemate.db.models import (
    Keyword,
    Movie,
    MovieCredit,
    MovieKeyword,
    Person,
    Rating,
    User,
)
from cinemate.db.session import create_all, make_engine
from cinemate.tmdb import TmdbClient, TmdbError, certification_country_for

NOW = datetime.now(UTC)


def _crew(job, pid, name):
    return {"id": pid, "name": name, "job": job, "profile_path": None}


MOVIE = {
    "id": 10,
    "title": "Leviathan",
    "release_date": "2014-06-05",
    "budget": 4_400_000,
    "revenue": 0,
    "tagline": "Truth",
    "overview": "o",
    "genres": [{"id": 18, "name": "Drama"}],
    "credits": {
        "cast": [
            {"id": 100 + i, "name": f"Actor {i}", "character": f"Role {i}", "order": i}
            for i in reversed(range(20))
        ],
        "crew": [
            _crew("Director", 1, "Dir A"),
            _crew("Director", 2, "Dir B"),
            _crew("Screenplay", 3, "W1"),
            _crew("Writer", 4, "W2"),
            _crew("Story", 99, "Ignored"),
            _crew("Writer", 5, "W3"),
            _crew("Writer", 6, "W4"),
            _crew("Producer", 7, "P1"),
            _crew("Producer", 8, "P2"),
            _crew("Producer", 9, "P3"),
            _crew("Producer", 11, "P4"),
            _crew("Executive Producer", 12, "Exec"),
            _crew("Original Music Composer", 13, "Comp"),
            _crew("Original Music Composer", 14, "Comp2"),
            _crew("Director", 1, "Dir A"),
        ],
    },
    "keywords": {"keywords": [{"id": 1, "name": "corruption"}, {"id": 2, "name": "russia"}]},
    "release_dates": {
        "results": [
            {"iso_3166_1": "DE", "release_dates": [{"certification": "12"}]},
            {
                "iso_3166_1": "US",
                "release_dates": [{"certification": ""}, {"certification": "R"}],
            },
            {"iso_3166_1": "RU", "release_dates": [{"certification": "18+"}]},
        ]
    },
}

TV = {
    "id": 20,
    "name": "Show",
    "first_air_date": "2011-04-17",
    "episode_run_time": [60],
    "number_of_seasons": 8,
    "number_of_episodes": 73,
    "created_by": [{"id": 50, "name": "Creator", "profile_path": "/c.jpg"}],
    "genres": [],
    "aggregate_credits": {
        "cast": [
            {"id": 60, "name": "Star", "order": 1, "roles": [{"character": "Hero"}]},
            {"id": 61, "name": "Lead", "order": 0, "roles": []},
        ],
        "crew": [
            {"id": 70, "name": "TV Dir", "jobs": [{"job": "Director"}]},
            {"id": 71, "name": "TV Comp", "jobs": [{"job": "Original Music Composer"}]},
        ],
    },
    "keywords": {"results": [{"id": 3, "name": "dragon"}]},
    "content_ratings": {
        "results": [{"iso_3166_1": "US", "rating": "TV-MA"}, {"iso_3166_1": "RU", "rating": "18+"}]
    },
}


def _client(payload):
    calls = []

    def http_get(url):
        calls.append(url)
        return 200, json.dumps(payload).encode()

    return TmdbClient("k", http_get=http_get), calls


def _by_role(details):
    result = {}
    for c in details.credits:
        result.setdefault(c.role, []).append(c)
    return result


def test_movie_credits_limited_per_role():
    client, calls = _client(MOVIE)
    details = client.fetch_details("movie", 10, extended=True)
    roles = _by_role(details)
    assert [c.person_id for c in roles["cast"]] == [100 + i for i in range(15)]
    assert roles["cast"][0].character == "Role 0"
    assert [c.person_id for c in roles["director"]] == [1, 2]
    assert [c.person_id for c in roles["writer"]] == [3, 4, 5]
    assert [c.person_id for c in roles["producer"]] == [7, 8, 9]
    assert [c.person_id for c in roles["composer"]] == [13]
    assert "creator" not in roles
    assert [c.order for c in roles["director"]] == [0, 1]
    query = calls[0]
    assert "credits" in query and "keywords" in query and "release_dates" in query
    assert "aggregate_credits" not in query


def test_basic_fetch_does_not_ask_for_extra_data():
    client, calls = _client(MOVIE)
    details = client.fetch_details("movie", 10)
    assert "credits" not in calls[0] and "keywords" not in calls[0]
    assert not details.extended and details.credits == [] and details.certification is None
    assert (details.budget, details.revenue, details.tagline) == (4_400_000, None, "Truth")


def test_tv_credits_creators_and_seasons():
    client, calls = _client(TV)
    details = client.fetch_details("tv", 20, extended=True)
    roles = _by_role(details)
    assert [c.person_id for c in roles["creator"]] == [50]
    assert [c.person_id for c in roles["cast"]] == [61, 60]
    assert [c.character for c in roles["cast"]] == [None, "Hero"]
    assert [c.person_id for c in roles["composer"]] == [71]
    assert "director" not in roles
    assert (details.number_of_seasons, details.number_of_episodes) == (8, 73)
    assert "aggregate_credits" in calls[0] and "content_ratings" in calls[0]


def test_keywords_in_both_formats():
    movie = _client(MOVIE)[0].fetch_details("movie", 10, extended=True)
    tv = _client(TV)[0].fetch_details("tv", 20, extended=True)
    assert movie.keywords == [(1, "corruption"), (2, "russia")]
    assert tv.keywords == [(3, "dragon")]


def test_certification_country_and_fallback():
    client, _ = _client(MOVIE)
    assert client.fetch_details("movie", 10, extended=True).certification == ("US", "R")
    ru = client.fetch_details("movie", 10, extended=True, certification_country="RU")
    assert ru.certification == ("RU", "18+")
    de = client.fetch_details("movie", 10, extended=True, certification_country="FR")
    assert de.certification == ("US", "R")
    tv, _ = _client(TV)
    assert tv.fetch_details("tv", 20, extended=True, certification_country="RU").certification == (
        "RU",
        "18+",
    )
    none, _ = _client({**MOVIE, "release_dates": {"results": []}})
    assert none.fetch_details("movie", 10, extended=True).certification is None
    assert certification_country_for("ru") == "RU"
    assert certification_country_for("en") == "US"
    assert certification_country_for(None) == "US"


def _session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return Session(engine)


def _movie(session, tmdb_id=10, tmdb_type="movie", title="M", rated=True, **kw):
    movie = Movie(title=title, tmdb_type=tmdb_type, tmdb_id=tmdb_id, **kw)
    session.add(movie)
    session.flush()
    if rated:
        user = User()
        session.add(user)
        session.flush()
        session.add(Rating(user_id=user.id, movie_id=movie.id, value=1))
    session.commit()
    return movie


def test_apply_extended_stores_without_duplicates():
    session = _session()
    movie = _movie(session)
    client, _ = _client(MOVIE)
    for _ in range(2):
        apply_extended(session, movie, client.fetch_details("movie", 10, extended=True))
        session.commit()
    assert session.scalar(select(func.count()).select_from(MovieCredit)) == 15 + 2 + 3 + 3 + 1
    assert session.scalar(select(func.count()).select_from(Person)) == 24
    assert session.scalar(select(func.count()).select_from(MovieKeyword)) == 2
    assert session.scalar(select(func.count()).select_from(Keyword)) == 2
    assert (movie.budget, movie.revenue, movie.tagline) == (4_400_000, None, "Truth")
    assert (movie.certification_country, movie.certification) == ("US", "R")
    assert movie.details_fetched_at is not None


def test_apply_extended_replaces_whole_cast():
    session = _session()
    movie = _movie(session)
    client, _ = _client(MOVIE)
    apply_extended(session, movie, client.fetch_details("movie", 10, extended=True))
    smaller = {
        **MOVIE,
        "credits": {"cast": [], "crew": [_crew("Director", 1, "Dir A")]},
        "keywords": {"keywords": [{"id": 2, "name": "russia"}]},
    }
    apply_extended(session, movie, _client(smaller)[0].fetch_details("movie", 10, extended=True))
    session.commit()
    assert session.scalars(select(MovieCredit.person_id)).all() == [1]
    assert session.scalars(select(MovieKeyword.keyword_id)).all() == [2]
    assert movie.budget == 4_400_000  # an empty answer never erases a stored value


def test_apply_extended_tv_seasons():
    session = _session()
    movie = _movie(session, 20, "tv")
    apply_extended(session, movie, _client(TV)[0].fetch_details("tv", 20, extended=True))
    assert (movie.number_of_seasons, movie.number_of_episodes) == (8, 73)


class FakeClient(TmdbClient):
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def fetch_details(self, tmdb_type, tmdb_id, extended=False, certification_country="US"):
        self.calls.append((tmdb_type, tmdb_id, extended))
        payload = self.payloads.get((tmdb_type, tmdb_id))
        if isinstance(payload, Exception):
            raise payload
        if payload is None:
            return None
        return _client(payload)[0].fetch_details(
            tmdb_type, tmdb_id, extended=extended, certification_country=certification_country
        )


def test_extended_selects_only_rated_movies_with_missing_or_stale_data():
    session = _session()
    _movie(session, 10, title="rated-new")
    _movie(session, 11, title="unrated", rated=False)
    _movie(session, 12, title="rated-fresh", details_fetched_at=NOW)
    _movie(session, 13, title="rated-stale", details_fetched_at=NOW - timedelta(days=40))
    session.add(Movie(title="no-pair"))
    session.commit()
    client = FakeClient({("movie", 10): MOVIE, ("movie", 13): MOVIE})
    stats = enrich_movies(session, client, extended=True, workers=1)
    assert stats.enriched == 2
    assert sorted(client.calls) == [("movie", 10, True), ("movie", 13, True)]
    assert session.scalar(select(Movie.certification).where(Movie.tmdb_id == 10)) == "R"


def test_extended_with_limit_and_exclusive_options():
    session = _session()
    _movie(session, 10, title="a")
    _movie(session, 11, title="b")
    client = FakeClient({("movie", 10): MOVIE, ("movie", 11): MOVIE})
    assert enrich_movies(session, client, extended=True, limit=1, workers=1).enriched == 1
    import pytest

    with pytest.raises(ValueError):
        enrich_movies(session, client, extended=True, missing_features=True)


def test_plain_enrich_refreshes_extended_only_where_it_exists():
    session = _session()
    stale = NOW - timedelta(days=40)
    _movie(session, 10, title="has-ext", tmdb_fetched_at=stale, details_fetched_at=stale)
    _movie(session, 11, title="basic", tmdb_fetched_at=stale)
    client = FakeClient({("movie", 10): MOVIE, ("movie", 11): MOVIE})
    enrich_movies(session, client, workers=1)
    assert sorted(client.calls) == [("movie", 10, True), ("movie", 11, False)]
    has_ext = session.scalar(select(Movie).where(Movie.tmdb_id == 10))
    basic = session.scalar(select(Movie).where(Movie.tmdb_id == 11))
    assert (
        has_ext.certification == "R"
        and has_ext.details_fetched_at is not None
        and has_ext.details_fetched_at.replace(tzinfo=UTC) > stale
    )
    assert basic.details_fetched_at is None and basic.certification is None


def test_ensure_extended_fetches_once_when_stale():
    session = _session()
    movie = _movie(session)
    client = FakeClient({("movie", 10): MOVIE})
    assert ensure_extended(session, client, movie, "RU") is True
    assert movie.certification == "18+"
    assert ensure_extended(session, client, movie, "RU") is False  # now fresh
    assert client.calls == [("movie", 10, True)]
    movie.details_fetched_at = NOW - timedelta(days=31)
    assert ensure_extended(session, client, movie) is True
    assert len(client.calls) == 2


def test_ensure_extended_is_best_effort():
    session = _session()
    movie = _movie(session)
    assert ensure_extended(session, None, movie) is False
    no_pair = Movie(title="x")
    session.add(no_pair)
    session.flush()
    client = FakeClient({("movie", 10): TmdbError("boom")})
    assert ensure_extended(session, client, no_pair) is False
    assert ensure_extended(session, client, movie) is False
    assert movie.details_fetched_at is None
    assert ensure_extended(session, FakeClient({}), movie) is False  # 404


def test_enrich_extended_cli(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    engine = make_engine(url)
    create_all(engine)
    with Session(engine) as session:
        _movie(session, 10)
    monkeypatch.setenv("TMDB_API_KEY", "k")
    monkeypatch.setattr(
        "cinemate.cli._bulk_client", lambda args, key: FakeClient({("movie", 10): MOVIE})
    )
    assert main(["enrich-movies", "--database-url", url, "--extended"]) == 0
    assert "movies enriched: 1" in capsys.readouterr().out
    assert main(["enrich-movies", "--database-url", url, "--extended", "--missing-features"]) == 2


def _card_client(client_impl):
    from fastapi.testclient import TestClient

    from cinemate.api.app import create_app

    app = create_app("sqlite:///:memory:", tmdb_client=client_impl)
    with Session(app.state.engine) as session:
        _movie(session, 10, title="Leviathan", rated=False)
    http = TestClient(app)
    http.__enter__()
    http.post("/api/session")
    return app, http


def test_card_open_fetches_extended_data_once():
    fake = FakeClient({("movie", 10): MOVIE})
    app, http = _card_client(fake)
    assert http.get("/api/movies/1", headers={"Accept-Language": "ru"}).status_code == 200
    assert http.get("/api/movies/1").status_code == 200
    assert fake.calls == [("movie", 10, True)]
    with Session(app.state.engine) as session:
        movie = session.get(Movie, 1)
        assert (movie.certification_country, movie.certification) == ("RU", "18+")
        assert session.scalar(select(func.count()).select_from(MovieCredit)) == 24


def test_card_survives_tmdb_error_and_missing_key():
    app, http = _card_client(FakeClient({("movie", 10): TmdbError("boom")}))
    assert http.get("/api/movies/1").status_code == 200
    app, http = _card_client(None)
    assert http.get("/api/movies/1").json()["title"] == "Leviathan"
