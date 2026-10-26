import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.cli import main
from cinemate.db.enrich import EnrichStats, enrich_movies
from cinemate.db.models import Movie
from cinemate.db.session import create_all, make_engine
from cinemate.tmdb import TmdbClient, TmdbMovie


class FakeClient(TmdbClient):
    def __init__(self, known):
        self.known = known
        self.requested = []

    def fetch_movie(self, tmdb_id):
        self.requested.append(tmdb_id)
        return self.known.get(tmdb_id)


def _session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    session = Session(engine)
    session.add_all(
        [
            Movie(title="A", tmdb_id=1),
            Movie(title="B", tmdb_id=2, overview="уже есть"),
            Movie(title="C", tmdb_id=None),
            Movie(title="D", tmdb_id=4),
            Movie(title="E", tmdb_id=5),
        ]
    )
    session.commit()
    return session


KNOWN = {
    1: TmdbMovie("О A", "/a.jpg", 90, "A orig", "Фильм А"),
    4: TmdbMovie("О D", None, 100, None, "D"),
}


def _overviews(session):
    return {m.title: m.overview for m in session.scalars(select(Movie))}


def test_enrich_fills_missing():
    session = _session()
    client = FakeClient(KNOWN)
    assert enrich_movies(session, client) == EnrichStats(enriched=2, not_found=1)
    assert client.requested == [1, 4, 5]
    movie = session.scalar(select(Movie).where(Movie.title == "A"))
    assert (movie.overview, movie.poster_path, movie.runtime, movie.original_title) == (
        "О A",
        "/a.jpg",
        90,
        "A orig",
    )
    assert _overviews(session)["B"] == "уже есть"


def test_enrich_is_idempotent():
    session = _session()
    enrich_movies(session, FakeClient(KNOWN))
    client = FakeClient(KNOWN)
    enrich_movies(session, client)
    assert client.requested == [5]


def test_enrich_limit():
    session = _session()
    client = FakeClient(KNOWN)
    assert enrich_movies(session, client, limit=1) == EnrichStats(1, 0)
    assert client.requested == [1]
    assert _overviews(session)["D"] is None


def test_cli_without_key(monkeypatch, capsys):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    assert main(["enrich-movies", "--database-url", "sqlite:///:memory:"]) != 0
    assert "TMDB_API_KEY" in capsys.readouterr().err


def test_cli_with_key_does_not_print_it(monkeypatch, capsys):
    monkeypatch.setenv("TMDB_API_KEY", "topsecret")
    assert main(["enrich-movies", "--database-url", "sqlite:///:memory:"]) == 0
    out = capsys.readouterr()
    assert "topsecret" not in out.out + out.err
    assert "movies enriched: 0" in out.out


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network access in tests")

    monkeypatch.setattr("urllib.request.urlopen", boom)


def test_cli_limit_must_be_positive(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "topsecret")
    with pytest.raises(SystemExit):
        main(["enrich-movies", "--limit", "0"])


def test_cli_tmdb_error_exit_code(monkeypatch, capsys):
    from cinemate.tmdb import TmdbError

    def fail(session, client, limit=None, refresh_titles=False):
        raise TmdbError("TMDB returned HTTP 500")

    monkeypatch.setenv("TMDB_API_KEY", "topsecret")
    monkeypatch.setattr("cinemate.cli.enrich_movies", fail)
    assert main(["enrich-movies", "--database-url", "sqlite:///:memory:"]) == 1
    out = capsys.readouterr()
    assert "HTTP 500" in out.err
    assert "topsecret" not in out.out + out.err


def _movie(session, title):
    return session.scalar(select(Movie).where(Movie.title == title))


def test_enrich_saves_title_ru_only_if_cyrillic():
    session = _session()
    enrich_movies(session, FakeClient(KNOWN))
    assert _movie(session, "A").title_ru == "Фильм А"
    assert _movie(session, "D").title_ru is None


def test_enrich_keeps_poster_without_overview():
    session = _session()
    known = {1: TmdbMovie(None, "/p.jpg", 90, "Orig", "Home Alone")}
    assert enrich_movies(session, FakeClient(known)) == EnrichStats(enriched=1, not_found=2)
    movie = _movie(session, "A")
    assert (movie.overview, movie.poster_path, movie.runtime) == (None, "/p.jpg", 90)
    assert movie.original_title == "Orig"
    assert movie.title_ru is None


def test_enrich_title_only_counts_as_enriched():
    session = _session()
    known = {1: TmdbMovie(None, None, None, None, "Один дома")}
    assert enrich_movies(session, FakeClient(known)) == EnrichStats(enriched=1, not_found=2)
    assert _movie(session, "A").title_ru == "Один дома"


def test_enrich_nothing_useful_is_not_found():
    session = _session()
    known = {1: TmdbMovie(None, None, 90, "Orig", "A")}
    assert enrich_movies(session, FakeClient(known)) == EnrichStats(enriched=0, not_found=3)


def test_enrich_skips_movie_with_poster_only():
    session = _session()
    movie = _movie(session, "A")
    movie.poster_path = "/x.jpg"
    session.commit()
    client = FakeClient(KNOWN)
    enrich_movies(session, client)
    assert 1 not in client.requested


def test_refresh_titles_fills_only_title_ru():
    session = _session()
    movie = _movie(session, "B")
    movie.title_ru = "Уже есть"
    _movie(session, "A").overview = "старое"
    session.commit()
    known = {
        1: TmdbMovie("новое", "/a.jpg", 90, "A orig", "Фильм А"),
        2: TmdbMovie("x", None, None, None, "Другое"),
    }
    client = FakeClient(known)
    assert enrich_movies(session, client, refresh_titles=True) == EnrichStats(
        enriched=1, not_found=2
    )
    assert client.requested == [1, 4, 5]
    a = _movie(session, "A")
    assert (a.title_ru, a.overview, a.poster_path, a.original_title) == (
        "Фильм А",
        "старое",
        None,
        None,
    )
    assert _movie(session, "B").title_ru == "Уже есть"


def test_refresh_titles_limit():
    session = _session()
    client = FakeClient(KNOWN)
    enrich_movies(session, client, limit=1, refresh_titles=True)
    assert client.requested == [1]


def test_cli_refresh_titles_flag(monkeypatch):
    seen = {}

    def fake(session, client, limit=None, refresh_titles=False):
        seen["refresh"] = refresh_titles
        return EnrichStats(0, 0)

    monkeypatch.setenv("TMDB_API_KEY", "k")
    monkeypatch.setattr("cinemate.cli.enrich_movies", fake)
    assert main(["enrich-movies", "--refresh-titles", "--database-url", "sqlite:///:memory:"]) == 0
    assert seen["refresh"] is True
