from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cinemate.cli import main
from cinemate.db.models import CatalogSync, Movie
from cinemate.db.session import create_all, make_engine
from cinemate.db.sync_changes import ChangesPeriodTooLong, sync_changes
from cinemate.tmdb import TmdbClient, TmdbDetails, TmdbError

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class FakeClient(TmdbClient):
    def __init__(self, changes, missing=(), fail_on=None, popularity=None):
        self._changes = changes  # tmdb_type -> ids
        self.missing = set(missing)
        self.fail_on = fail_on
        self.popularity = popularity or {}
        self.requested = []
        self.windows = []

    def changes(self, tmdb_type, start, end):
        self.windows.append((tmdb_type, start, end))
        yield from self._changes.get(tmdb_type, [])

    def fetch_details(self, tmdb_type, tmdb_id):
        self.requested.append((tmdb_type, tmdb_id))
        if (tmdb_type, tmdb_id) == self.fail_on:
            raise TmdbError("boom")
        if (tmdb_type, tmdb_id) in self.missing:
            return None
        return TmdbDetails(
            tmdb_type=tmdb_type,
            tmdb_id=tmdb_id,
            title=f"New {tmdb_id}",
            original_title=None,
            year=2026,
            poster_path="/new.jpg",
            runtime=None,
            popularity=self.popularity.get(tmdb_id, 5.0),
            imdb_id=f"tt{tmdb_id:07d}",
        )


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with sessionmaker(engine)() as s:
        yield s


def _run(session, client, **kw):
    kw.setdefault("now", NOW)
    return sync_changes(session, client, **kw)


def test_updates_existing_without_erasing_and_creates_new(session):
    session.add(
        Movie(
            title="Old",
            genres=[],
            tmdb_type="movie",
            tmdb_id=1,
            overview="kept",
            year=2000,
            tmdb_fetched_at=NOW - timedelta(days=60),
        )
    )
    session.commit()
    stats = _run(session, FakeClient({"movie": [1, 2]}), types=("movie",))
    assert (stats.changed, stats.updated, stats.added, stats.not_found) == (2, 1, 1, 0)
    old = session.scalar(select(Movie).where(Movie.tmdb_id == 1))
    assert (old.title, old.year, old.overview, old.poster_path) == (
        "New 1",
        2026,
        "kept",
        "/new.jpg",
    )
    assert old.tmdb_popularity == 5.0
    assert old.tmdb_fetched_at is not None
    assert session.scalar(select(Movie.title).where(Movie.tmdb_id == 2)) == "New 2"


def test_not_found_is_counted(session):
    stats = _run(session, FakeClient({"tv": [7]}, missing=[("tv", 7)]), types=("tv",))
    assert (stats.not_found, stats.added) == (1, 0)


def test_min_popularity_blocks_new_but_not_existing(session):
    session.add(Movie(title="Old", genres=[], tmdb_type="movie", tmdb_id=1))
    session.commit()
    client = FakeClient({"movie": [1, 2, 3]}, popularity={1: 0.1, 2: 0.1, 3: 9.0})
    stats = _run(session, client, types=("movie",), min_popularity=1.0)
    assert (stats.updated, stats.added, stats.skipped_low_popularity) == (1, 1, 1)
    assert session.scalar(select(Movie).where(Movie.tmdb_id == 2)) is None


def test_period_defaults_and_state_saved(session):
    client = FakeClient({"movie": [1]})
    _run(session, client, types=("movie",))
    assert client.windows == [("movie", (NOW - timedelta(days=1)).date(), NOW.date())]
    state = session.get(CatalogSync, "movie")
    assert state.changes_synced_until.replace(tzinfo=UTC) == NOW

    later = NOW + timedelta(days=3)
    client2 = FakeClient({"movie": []})
    _run(session, client2, types=("movie",), now=later)
    assert client2.windows == [("movie", NOW.date(), later.date())]


def test_since_used_without_state(session):
    client = FakeClient({})
    _run(session, client, types=("tv",), since=datetime(2026, 10, 20, tzinfo=UTC))
    assert client.windows[0][1].isoformat() == "2026-10-20"


def test_state_not_advanced_on_error_and_rerun_skips_done(session):
    client = FakeClient({"movie": [1, 2, 3]}, fail_on=("movie", 3))
    with pytest.raises(TmdbError):
        _run(session, client, types=("movie",))
    assert session.get(CatalogSync, "movie") is None
    assert {m.tmdb_id for m in session.scalars(select(Movie))} == {1, 2}

    retry = FakeClient({"movie": [1, 2, 3]})
    stats = _run(session, retry, types=("movie",), now=NOW + timedelta(minutes=5))
    assert retry.requested == [("movie", 3)]
    assert (stats.up_to_date, stats.added) == (2, 1)
    assert session.get(CatalogSync, "movie") is not None


def test_same_day_rerun_requests_almost_nothing(session):
    _run(session, FakeClient({"movie": [1, 2]}), types=("movie",))
    again = FakeClient({"movie": [1, 2]})
    stats = _run(session, again, types=("movie",), now=NOW + timedelta(hours=1))
    assert again.requested == []
    assert stats.up_to_date == 2


def test_limit_keeps_period_open(session):
    client = FakeClient({"movie": [1, 2, 3]})
    stats = _run(session, client, types=("movie",), limit=2)
    assert (stats.added, stats.remaining) == (2, 1)
    assert session.get(CatalogSync, "movie") is None


def test_period_over_90_days_refused_before_any_request(session):
    client = FakeClient({"movie": [1]})
    with pytest.raises(ChangesPeriodTooLong):
        _run(session, client, types=("movie",), since=NOW - timedelta(days=91))
    assert client.windows == [] and client.requested == []


def test_cli_too_long_period_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TMDB_API_KEY", "k")
    url = f"sqlite:///{tmp_path / 'c.db'}"
    code = main(["sync-catalog", "--changes", "--since", "2020-01-01", "--database-url", url])
    assert code == 2
    assert "full load" in capsys.readouterr().err


def test_cli_since_requires_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "k")
    url = f"sqlite:///{tmp_path / 'c.db'}"
    assert main(["sync-catalog", "--since", "2026-10-01", "--database-url", url]) == 2
