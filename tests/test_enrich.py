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
    1: TmdbMovie("О A", "/a.jpg", 90, "A orig"),
    4: TmdbMovie("О D", None, 100, None),
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

    def fail(session, client, limit=None):
        raise TmdbError("TMDB returned HTTP 500")

    monkeypatch.setenv("TMDB_API_KEY", "topsecret")
    monkeypatch.setattr("cinemate.cli.enrich_movies", fail)
    assert main(["enrich-movies", "--database-url", "sqlite:///:memory:"]) == 1
    out = capsys.readouterr()
    assert "HTTP 500" in out.err
    assert "topsecret" not in out.out + out.err
