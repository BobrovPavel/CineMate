import gzip
import json
import random
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from cinemate.cli import main
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, MovieExternalId, Rating, User
from cinemate.db.session import create_all, make_engine
from cinemate.db.sync_catalog import (
    CatalogSyncError,
    SyncStats,
    export_name,
    sync_catalog,
)
from cinemate.services.onboarding import onboarding_for_user
from cinemate.services.recommendations import get_recommendations
from cinemate.tmdb import TmdbClient, TmdbDetails, TmdbError

DAY = date(2026, 10, 27)

MOVIES = [
    {"adult": False, "id": 1, "original_title": "Low", "popularity": 0.5, "video": False},
    {"adult": False, "id": 2, "original_title": "Top", "popularity": 50.0, "video": False},
    {"adult": True, "id": 3, "original_title": "Adult", "popularity": 99.0, "video": False},
    {"adult": False, "id": 4, "original_title": "Clip", "popularity": 30.0, "video": True},
    {"adult": False, "id": 5, "original_title": "Mid", "popularity": 10.0, "video": False},
    {"adult": False, "id": 6, "original_title": "Gone", "popularity": 20.0, "video": False},
]
TV = [
    {"id": 10, "original_name": "Show", "popularity": 25.0},
    {"id": 11, "original_name": "Tiny", "popularity": 0.1},
]


def _gz(records):
    return gzip.compress(("\n".join(json.dumps(r) for r in records) + "\n").encode())


class FakeHttp:
    def __init__(self, files):
        self.files = files  # file name -> bytes
        self.requests = []

    def __call__(self, url):
        name = url.rsplit("/", 1)[1]
        self.requests.append(name)
        if name in self.files:
            return 200, self.files[name]
        return 404, b""


class FakeClient(TmdbClient):
    def __init__(self, missing=(), fail_on=None):
        self.missing = set(missing)
        self.fail_on = fail_on
        self.requested = []

    def fetch_details(self, tmdb_type, tmdb_id):
        self.requested.append((tmdb_type, tmdb_id))
        if (tmdb_type, tmdb_id) == self.fail_on:
            raise TmdbError("boom")
        if (tmdb_type, tmdb_id) in self.missing:
            return None
        return TmdbDetails(
            tmdb_type=tmdb_type,
            tmdb_id=tmdb_id,
            title=f"{tmdb_type}{tmdb_id}",
            original_title=None,
            year=2000,
            poster_path=None,
            runtime=None,
            imdb_id=f"tt{tmdb_id:07d}",
        )


@pytest.fixture
def http():
    return FakeHttp(
        {export_name("movie", DAY): _gz(MOVIES), export_name("tv", DAY): _gz(TV)},
    )


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return sessionmaker(engine)


@pytest.fixture
def session(factory):
    with factory() as s:
        yield s


def _run(session, http, tmp_path, client=None, **kw):
    kw.setdefault("day", DAY)
    return sync_catalog(session, client or FakeClient(), export_dir=tmp_path, http_get=http, **kw)


def _pairs(session):
    return {tuple(r) for r in session.execute(select(Movie.tmdb_type, Movie.tmdb_id))}


def test_filters_and_summary(session, http, tmp_path):
    client = FakeClient(missing=[("movie", 6)])
    stats = _run(session, http, tmp_path, client, min_popularity=1, workers=1)
    assert stats == SyncStats(
        in_export=8,
        skipped_adult=1,
        skipped_video=1,
        skipped_low_popularity=2,
        already_present=0,
        popularity_updated=0,
        added=3,
        not_found=1,
        remaining=0,
    )
    assert _pairs(session) == {("movie", 2), ("movie", 5), ("tv", 10)}


def test_include_video_loads_video_records(session, http, tmp_path):
    stats = _run(session, http, tmp_path, include_video=True, min_popularity=1)
    assert stats.skipped_video == 0
    assert ("movie", 4) in _pairs(session)


def test_single_type(session, http, tmp_path):
    stats = _run(session, http, tmp_path, types=["tv"])
    assert stats.in_export == 2
    assert {t for t, _ in _pairs(session)} == {"tv"}
    assert export_name("movie", DAY) not in http.requests


def test_new_pairs_go_by_descending_popularity(session, http, tmp_path):
    client = FakeClient()
    _run(session, http, tmp_path, client, min_popularity=1, workers=1)
    assert client.requested == [("movie", 2), ("tv", 10), ("movie", 6), ("movie", 5)]


def test_new_movie_gets_popularity_fetch_time_and_imdb(session, http, tmp_path):
    _run(session, http, tmp_path, min_popularity=1)
    movie = session.scalar(select(Movie).where(Movie.tmdb_id == 2, Movie.tmdb_type == "movie"))
    assert movie.tmdb_popularity == 50.0
    assert movie.tmdb_fetched_at is not None
    assert session.get(MovieExternalId, ("imdb", "tt0000002")).movie_id == movie.id


def test_existing_pairs_are_not_requested_but_popularity_is_updated(session, http, tmp_path):
    session.add_all(
        [
            Movie(title="Top", tmdb_type="movie", tmdb_id=2, tmdb_popularity=1.0),
            # below --min-popularity and video: still refreshed, it is already stored
            Movie(title="Low", tmdb_type="movie", tmdb_id=1),
            Movie(title="Clip", tmdb_type="movie", tmdb_id=4),
            # same id, other type
            Movie(title="Other", tmdb_type="tv", tmdb_id=2),
        ]
    )
    session.commit()
    client = FakeClient()
    stats = _run(session, http, tmp_path, client, min_popularity=1, workers=1)
    assert ("movie", 2) not in client.requested
    assert stats.already_present == 3
    assert stats.popularity_updated == 3
    by_title = {m.title: m.tmdb_popularity for m in session.scalars(select(Movie))}
    assert by_title["Top"] == 50.0
    assert by_title["Low"] == 0.5
    assert by_title["Clip"] == 30.0
    assert by_title["Other"] is None


def test_limit_and_resume_without_duplicates(session, http, tmp_path):
    first = _run(session, http, tmp_path, limit=2, min_popularity=1)
    assert (first.added, first.remaining) == (2, 2)
    assert _pairs(session) == {("movie", 2), ("tv", 10)}
    client = FakeClient()
    second = _run(session, http, tmp_path, client, min_popularity=1, workers=1)
    assert client.requested == [("movie", 6), ("movie", 5)]
    assert (second.already_present, second.added, second.remaining) == (2, 2, 0)
    total = session.scalar(select(func.count()).select_from(Movie))
    assert total == 4 == len(_pairs(session))


def test_interrupted_run_keeps_what_is_written(session, factory, http, tmp_path):
    client = FakeClient(fail_on=("movie", 6))
    with pytest.raises(TmdbError):
        _run(session, http, tmp_path, client, min_popularity=1, workers=1)
    with factory() as other:
        assert _pairs(other) == {("movie", 2), ("tv", 10)}


def test_keyboard_interrupt_commits_written_records(session, factory, http, tmp_path):
    class Interrupt(FakeClient):
        def fetch_details(self, tmdb_type, tmdb_id):
            if (tmdb_type, tmdb_id) == ("movie", 6):
                raise KeyboardInterrupt
            return super().fetch_details(tmdb_type, tmdb_id)

    with pytest.raises(KeyboardInterrupt):
        _run(session, http, tmp_path, Interrupt(), min_popularity=1, workers=1)
    with factory() as other:
        assert _pairs(other) == {("movie", 2), ("tv", 10)}


def test_commits_every_500_and_reports_progress(session, tmp_path):
    records = [{"id": i, "popularity": 5.0, "video": False, "adult": False} for i in range(1, 1202)]
    http = FakeHttp({export_name("movie", DAY): _gz(records)})
    ticks = iter(range(0, 10_000, 10))
    seen = []
    stats = sync_catalog(
        session,
        FakeClient(),
        types=["movie"],
        day=DAY,
        export_dir=tmp_path,
        http_get=http,
        progress=lambda *a: seen.append(a),
        clock=lambda: float(next(ticks)),
    )
    assert stats.added == 1201
    assert [s[:2] for s in seen] == [(1000, 1201)]
    done, total, rate, eta = seen[0]
    assert rate > 0 and eta is not None and eta > 0


def test_export_is_downloaded_once(session, http, tmp_path):
    _run(session, http, tmp_path, types=["tv"])
    _run(session, http, tmp_path, types=["tv"])
    assert http.requests == [export_name("tv", DAY)]
    assert (tmp_path / export_name("tv", DAY)).exists()
    assert not list(tmp_path.glob("*.part"))


def test_falls_back_to_yesterday_when_today_is_not_published(session, tmp_path):
    yesterday = date(2026, 10, 26)
    http = FakeHttp({export_name("tv", yesterday): _gz(TV)})
    stats = _run(session, http, tmp_path, types=["tv"])
    assert http.requests == [export_name("tv", DAY), export_name("tv", yesterday)]
    assert stats.added == 2


def test_error_when_no_export_for_two_days(session, tmp_path):
    with pytest.raises(CatalogSyncError, match="no TMDB tv export"):
        _run(session, FakeHttp({}), tmp_path, types=["tv"])


def test_corrupt_export_is_reported(session, tmp_path):
    (tmp_path / export_name("tv", DAY)).write_bytes(b"not gzip")
    with pytest.raises(CatalogSyncError, match="cannot read"):
        _run(session, FakeHttp({}), tmp_path, types=["tv"])


def test_blank_and_broken_lines_are_skipped(session, tmp_path):
    body = gzip.compress(b'{"id": 10, "popularity": 1.5}\n\nnot json\n[1]\n{"id": 11}\n')
    http = FakeHttp({export_name("tv", DAY): body})
    stats = _run(session, http, tmp_path, types=["tv"])
    assert (stats.in_export, stats.added) == (2, 2)


def test_catalog_only_movies_stay_out_of_onboarding_and_fallback(factory, http, tmp_path):
    with factory() as s:
        s.add_all([Movie(id=i, title=f"rated{i}", genres=["Drama"]) for i in range(1, 4)])
        s.add_all([User(id=i) for i in range(1, 7)])
        s.flush()
        s.add_all([Rating(user_id=u, movie_id=m, value=1) for u in range(1, 6) for m in (1, 2, 3)])
        s.commit()
        _run(s, http, tmp_path)
        assert s.scalar(select(func.count()).select_from(Movie)) > 3
        store = MatrixStore(factory)
        user = s.get(User, 6)
        onboarding = onboarding_for_user(s, store, user, n=20)
        result = get_recommendations(s, store, user, rng=random.Random(0))
    assert {m.id for m in onboarding} <= {1, 2, 3}
    assert result.strategy == "fallback"
    assert {i.movie.id for i in result.items} <= {1, 2, 3}


def test_cli_requires_api_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    assert main(["sync-catalog", "--database-url", url]) == 2
    assert "TMDB_API_KEY" in capsys.readouterr().err


def test_cli_runs_with_fake_transport(monkeypatch, tmp_path, capsys, http):
    monkeypatch.setenv("TMDB_API_KEY", "k")
    monkeypatch.setattr("cinemate.db.sync_catalog.urllib_get", http)
    monkeypatch.setattr("cinemate.cli.TmdbClient", lambda key, **kw: FakeClient())
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    export_dir = tmp_path / "exports"
    code = main(
        ["sync-catalog", "--database-url", url, "--type", "tv", "--date", "2026-10-27",
         "--export-dir", str(export_dir), "--limit", "1", "--min-popularity", "1"]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0
    assert "added: 1" in out and "remaining: 0" in out
    assert (export_dir / export_name("tv", DAY)).exists()
