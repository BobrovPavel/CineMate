from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.cli import main
from cinemate.db.catalog import import_from_tmdb
from cinemate.db.enrich import EnrichStats, enrich_movies
from cinemate.db.models import Movie, MovieExternalId
from cinemate.db.session import create_all, make_engine
from cinemate.tmdb import TmdbClient, TmdbDetails, TmdbError

NOW = datetime.now(UTC)


def _details(tmdb_type="movie", tmdb_id=1, **kw):
    base = {
        "title": "T",
        "original_title": None,
        "year": None,
        "poster_path": None,
        "runtime": None,
    }
    return TmdbDetails(tmdb_type=tmdb_type, tmdb_id=tmdb_id, **{**base, **kw})


class FakeClient(TmdbClient):
    def __init__(self, known):
        self.known = known
        self.requested = []

    def fetch_details(self, tmdb_type, tmdb_id):
        self.requested.append((tmdb_type, tmdb_id))
        return self.known.get((tmdb_type, tmdb_id))


def _session(movies=None):
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    session = Session(engine)
    session.add_all(movies or [])
    session.commit()
    return session


def _movie(session, title):
    return session.scalar(select(Movie).where(Movie.title == title))


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def test_tv_is_requested_as_tv_not_movie():
    session = _session([Movie(title="GoT", tmdb_type="tv", tmdb_id=1399)])
    client = FakeClient({("tv", 1399): _details("tv", 1399, title="Game of Thrones")})
    assert enrich_movies(session, client) == EnrichStats(1, 0, 0)
    assert client.requested == [("tv", 1399)]
    assert _movie(session, "Game of Thrones") is not None


def test_enrich_writes_fields_and_fetched_at():
    session = _session([Movie(title="A", tmdb_type="movie", tmdb_id=1, genres=["Drama"])])
    details = _details(
        title="Alien",
        original_title="Alien orig",
        title_ru="Чужой",
        year=1979,
        poster_path="/a.jpg",
        runtime=117,
        overview="eng",
        overview_ru="рус",
        imdb_id="tt0078748",
    )
    enrich_movies(session, FakeClient({("movie", 1): details}))
    movie = _movie(session, "Alien")
    assert (movie.original_title, movie.title_ru, movie.year) == ("Alien orig", "Чужой", 1979)
    assert (movie.overview, movie.poster_path, movie.runtime) == ("рус", "/a.jpg", 117)
    assert movie.genres == ["Drama"]
    assert abs(_aware(movie.tmdb_fetched_at) - datetime.now(UTC)) < timedelta(minutes=1)
    assert session.get(MovieExternalId, ("imdb", "tt0078748")).movie_id == movie.id


def test_empty_tmdb_values_do_not_erase():
    session = _session(
        [Movie(title="A", tmdb_type="movie", tmdb_id=1, overview="old", poster_path="/old.jpg")]
    )
    enrich_movies(session, FakeClient({("movie", 1): _details(title="A")}))
    movie = _movie(session, "A")
    assert (movie.overview, movie.poster_path) == ("old", "/old.jpg")
    assert movie.tmdb_fetched_at is not None


def test_english_overview_used_without_russian():
    session = _session([Movie(title="A", tmdb_type="movie", tmdb_id=1)])
    enrich_movies(session, FakeClient({("movie", 1): _details(title="A", overview="eng")}))
    assert _movie(session, "A").overview == "eng"


def test_imdb_conflict_is_suppressed():
    session = _session(
        [
            Movie(title="A", tmdb_type="movie", tmdb_id=1),
            Movie(title="B", tmdb_type="movie", tmdb_id=2),
        ]
    )
    client = FakeClient(
        {
            ("movie", 1): _details(title="A", imdb_id="tt1"),
            ("movie", 2): _details("movie", 2, title="B", imdb_id="tt1"),
        }
    )
    assert enrich_movies(session, client) == EnrichStats(2, 0, 0)
    assert _movie(session, "B").tmdb_fetched_at is not None


def test_stale_boundaries():
    days = 30
    session = _session(
        [
            Movie(
                title="old", tmdb_type="movie", tmdb_id=1, tmdb_fetched_at=NOW - timedelta(days=31)
            ),
            Movie(
                title="edge",
                tmdb_type="movie",
                tmdb_id=2,
                tmdb_fetched_at=NOW - timedelta(days=days - 1),
            ),
            Movie(
                title="fresh",
                tmdb_type="movie",
                tmdb_id=3,
                tmdb_fetched_at=NOW - timedelta(hours=12),
            ),
        ]
    )
    client = FakeClient({})
    enrich_movies(session, client, stale_days=days)
    assert client.requested == [("movie", 1)]
    client = FakeClient({})
    enrich_movies(session, client, stale_days=1)
    assert sorted(client.requested) == [("movie", 1), ("movie", 2)]


def test_null_first_then_oldest():
    session = _session(
        [
            Movie(
                title="b", tmdb_type="movie", tmdb_id=1, tmdb_fetched_at=NOW - timedelta(days=40)
            ),
            Movie(
                title="c", tmdb_type="movie", tmdb_id=2, tmdb_fetched_at=NOW - timedelta(days=90)
            ),
            Movie(title="a", tmdb_type="movie", tmdb_id=3),
        ]
    )
    client = FakeClient({})
    enrich_movies(session, client)
    assert client.requested == [("movie", 3), ("movie", 2), ("movie", 1)]
    client = FakeClient({})
    enrich_movies(session, client, limit=1)
    assert client.requested == [("movie", 3)]


@pytest.mark.parametrize("days", [0, 181])
def test_stale_days_out_of_range(days):
    with pytest.raises(ValueError):
        enrich_movies(_session(), FakeClient({}), stale_days=days)


def test_not_found_leaves_movie_untouched():
    old = NOW - timedelta(days=60)
    session = _session(
        [Movie(title="A", tmdb_type="movie", tmdb_id=1, overview="old", tmdb_fetched_at=old)]
    )
    assert enrich_movies(session, FakeClient({})) == EnrichStats(0, 1, 0)
    movie = _movie(session, "A")
    assert movie.overview == "old"
    assert _aware(movie.tmdb_fetched_at) == old


def test_skips_movies_without_pair():
    session = _session(
        [
            Movie(title="C"),
            Movie(title="D", tmdb_id=4),
            Movie(title="A", tmdb_type="movie", tmdb_id=1),
        ]
    )
    client = FakeClient({("movie", 1): _details(title="A")})
    assert enrich_movies(session, client) == EnrichStats(1, 0, 2)
    assert client.requested == [("movie", 1)]


def test_tmdb_error_commits_progress():
    session = _session(
        [
            Movie(title="A", tmdb_type="movie", tmdb_id=1),
            Movie(title="B", tmdb_type="movie", tmdb_id=2),
        ]
    )

    class Failing(FakeClient):
        def fetch_details(self, tmdb_type, tmdb_id):
            if tmdb_id == 2:
                raise TmdbError("HTTP 500")
            return _details(title="A2")

    with pytest.raises(TmdbError):
        enrich_movies(session, Failing({}))
    session.rollback()
    assert _movie(session, "A2").tmdb_fetched_at is not None


def test_commits_in_batches(monkeypatch):
    monkeypatch.setattr("cinemate.db.enrich.COMMIT_EVERY", 2)
    session = _session([Movie(title=str(i), tmdb_type="movie", tmdb_id=i) for i in range(1, 4)])
    commits = []
    real = session.commit
    session.commit = lambda: (commits.append(1), real())[1]
    client = FakeClient({("movie", i): _details("movie", i, title=f"t{i}") for i in range(1, 4)})
    enrich_movies(session, client)
    assert len(commits) == 2  # after the 2nd movie and the final one


def test_refresh_titles_only_without_title_ru_and_ignores_age():
    session = _session(
        [
            Movie(title="A", tmdb_type="movie", tmdb_id=1),
            Movie(title="B", tmdb_type="movie", tmdb_id=2, title_ru="Б"),
            Movie(title="C", tmdb_type="tv", tmdb_id=3, tmdb_fetched_at=NOW),
        ]
    )
    client = FakeClient({("tv", 3): _details("tv", 3, title="C", title_ru="Це")})
    stats = enrich_movies(session, client, refresh_titles=True)
    assert client.requested == [("movie", 1), ("tv", 3)]
    assert stats == EnrichStats(1, 1, 0)
    assert _movie(session, "C").title_ru == "Це"
    client = FakeClient({})
    enrich_movies(session, client, refresh_titles=True, limit=1)
    assert client.requested == [("movie", 1)]


def test_import_from_tmdb_sets_fetched_at():
    session = _session()
    client = FakeClient({("tv", 5): _details("tv", 5, title="Show")})
    movie = import_from_tmdb(session, client, "tv", 5)
    assert abs(_aware(movie.tmdb_fetched_at) - datetime.now(UTC)) < timedelta(minutes=1)


def test_cli_without_key(monkeypatch, capsys):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    assert main(["enrich-movies", "--database-url", "sqlite:///:memory:"]) != 0
    assert "TMDB_API_KEY" in capsys.readouterr().err


def test_cli_with_key_does_not_print_it(monkeypatch, capsys):
    monkeypatch.setenv("TMDB_API_KEY", "topsecret")
    assert main(["enrich-movies", "--database-url", "sqlite:///:memory:"]) == 0
    out = capsys.readouterr()
    assert "topsecret" not in out.out + out.err
    assert "movies enriched: 0, not found: 0, skipped (no TMDB pair): 0" in out.out


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network access in tests")

    monkeypatch.setattr("urllib.request.urlopen", boom)


def test_cli_limit_must_be_positive(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "topsecret")
    with pytest.raises(SystemExit):
        main(["enrich-movies", "--limit", "0"])


@pytest.mark.parametrize("days", ["0", "181", "x"])
def test_cli_stale_days_range(monkeypatch, days):
    monkeypatch.setenv("TMDB_API_KEY", "k")
    with pytest.raises(SystemExit):
        main(["enrich-movies", "--stale-days", days])


def test_cli_tmdb_error_exit_code(monkeypatch, capsys):
    def fail(session, client, **kwargs):
        raise TmdbError("TMDB returned HTTP 500")

    monkeypatch.setenv("TMDB_API_KEY", "topsecret")
    monkeypatch.setattr("cinemate.cli.enrich_movies", fail)
    assert main(["enrich-movies", "--database-url", "sqlite:///:memory:"]) == 1
    out = capsys.readouterr()
    assert "HTTP 500" in out.err
    assert "topsecret" not in out.out + out.err


def test_cli_passes_flags(monkeypatch):
    seen = {}

    def fake(session, client, **kwargs):
        seen.update(kwargs)
        return EnrichStats(0, 0)

    monkeypatch.setenv("TMDB_API_KEY", "k")
    monkeypatch.setattr("cinemate.cli.enrich_movies", fake)
    argv = ["enrich-movies", "--refresh-titles", "--stale-days", "7", "--database-url"]
    assert main([*argv, "sqlite:///:memory:"]) == 0
    assert seen["refresh_titles"] is True
    assert seen["stale_days"] == 7
