"""``enrich_movies`` in batches: long strings, failed records, progress, ordering, interrupts."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from cinemate.api.app import create_app
from cinemate.db.enrich import MAX_FAILURE_LINES, EnrichStats, enrich_movies
from cinemate.db.models import (
    Collection,
    Company,
    Keyword,
    Movie,
    MovieCredit,
    Person,
    Rating,
    User,
)
from cinemate.db.session import create_all, make_engine
from cinemate.db.sync_changes import sync_changes
from cinemate.db.text import fit
from cinemate.tmdb import TmdbClient, TmdbCredit, TmdbDetails, TmdbError

NOW = datetime.now(UTC)


def _details(tmdb_type="movie", tmdb_id=1, **kw):
    base = {
        "title": f"T{tmdb_id}",
        "original_title": None,
        "year": None,
        "poster_path": None,
        "runtime": None,
    }
    return TmdbDetails(tmdb_type=tmdb_type, tmdb_id=tmdb_id, **{**base, **kw})


class FakeClient(TmdbClient):
    def __init__(self, known=None, fail_on=None, interrupt_on=None):
        self.known = known
        self.requested = []
        self.fail_on = fail_on
        self.interrupt_on = interrupt_on

    def fetch_details(self, tmdb_type, tmdb_id, extended=False, **kwargs):
        self.requested.append((tmdb_type, tmdb_id))
        if tmdb_id == self.interrupt_on:
            raise KeyboardInterrupt
        if tmdb_id == self.fail_on:
            raise TmdbError("boom")
        if self.known is not None:
            return self.known.get((tmdb_type, tmdb_id))
        return _details(tmdb_type, tmdb_id, extended=extended)


def _session(movies=()):
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    session = Session(engine)
    session.add_all(movies)
    session.commit()
    return session


def _m(i, **kw):
    return Movie(title=f"m{i}", tmdb_type="movie", tmdb_id=i, **kw)


def _ids(session, fetched):
    column = Movie.tmdb_fetched_at
    where = column.is_not(None) if fetched else column.is_(None)
    return {m.tmdb_id for m in session.scalars(select(Movie).where(where))}


def _movies(n, **kw):
    return [Movie(title=f"m{i}", tmdb_type="movie", tmdb_id=i, **kw) for i in range(1, n + 1)]


def test_fit_cuts_to_column_length_with_ellipsis():
    limit = Movie.title.type.length
    assert fit(Movie.title, "x" * limit) == "x" * limit
    cut = fit(Movie.title, "x" * (limit + 50))
    assert len(cut) == limit and cut.endswith("…")
    assert fit(Movie.title, None) is None
    assert fit(Movie.overview, "y" * 100_000) == "y" * 100_000  # Text has no length
    assert fit(Movie.year, 1999) == 1999


def test_long_strings_are_cut_and_written():
    session = _session(_movies(1))
    session.add(User(id=1))
    session.flush()
    session.add(Rating(user_id=1, movie_id=1, value=1))
    session.commit()
    long = "я" * 2000
    credits = [
        TmdbCredit(7, long, long, "cast", long, 0),
        TmdbCredit(8, "Dir", None, "director", None, 0),
    ]
    details = _details(
        title=long,
        original_title=long,
        title_ru=long,
        poster_path=long,
        tagline=long,
        extended=True,
        credits=credits,
        keywords=[(1, long)],
        collection=(5, long),
        companies=[(6, long, long)],
        certification=("US", "x" * 100),
        original_language="en-US-long-tag",
    )
    stats = enrich_movies(session, FakeClient({("movie", 1): details}), extended=True, workers=1)
    assert stats == EnrichStats(1, 0, 0, 0)
    movie = session.scalar(select(Movie))
    for field in ("title", "original_title", "title_ru", "poster_path", "tagline", "certification"):
        assert len(getattr(movie, field)) == getattr(Movie, field).type.length, field
        assert getattr(movie, field).endswith("…")
    credit = session.scalar(select(MovieCredit).where(MovieCredit.role == "cast"))
    assert len(credit.character) == MovieCredit.character.type.length
    assert len(session.get(Person, 7).name) == Person.name.type.length
    assert len(session.get(Keyword, 1).name) == Keyword.name.type.length
    assert len(session.get(Collection, 5).name) == Collection.name.type.length
    assert len(session.get(Company, 6).name) == Company.name.type.length


def test_db_error_on_one_movie_does_not_stop_the_batch(monkeypatch):
    import cinemate.db.enrich as module

    real = module.apply_details

    def apply(session, movie, details):
        if movie.tmdb_id == 2:
            raise DataError("INSERT", {}, Exception("too long"))
        real(session, movie, details)

    monkeypatch.setattr(module, "apply_details", apply)
    session = _session(_movies(3))
    lines = []
    stats = enrich_movies(session, FakeClient(), workers=1, report=lines.append)
    assert (stats.enriched, stats.failed) == (2, 1)
    done = {
        m.tmdb_id for m in session.scalars(select(Movie).where(Movie.tmdb_fetched_at.is_(None)))
    }
    assert done == {2}
    failed = [line for line in lines if line.startswith("failed")]
    assert failed == ["failed: movie id 2, TMDB movie 2: DataError"]


def test_failure_lines_are_limited(monkeypatch):
    import cinemate.db.enrich as module

    def apply(session, movie, details):
        raise DataError("INSERT", {}, Exception("x"))

    monkeypatch.setattr(module, "apply_details", apply)
    n = MAX_FAILURE_LINES + 5
    session = _session(_movies(n))
    lines = []
    stats = enrich_movies(session, FakeClient(), workers=1, report=lines.append)
    assert stats.failed == n
    assert len([line for line in lines if line.startswith("failed:")]) == MAX_FAILURE_LINES


def test_tmdb_error_stops_but_keeps_written_batches(monkeypatch):
    monkeypatch.setattr("cinemate.db.enrich.BATCH_SIZE", 2)
    session = _session(_movies(5))
    with pytest.raises(TmdbError):
        enrich_movies(session, FakeClient(fail_on=4), workers=1)
    fetched = {
        m.tmdb_id for m in session.scalars(select(Movie).where(Movie.tmdb_fetched_at.is_not(None)))
    }
    assert fetched == {1, 2, 3}


def test_old_batches_do_not_stay_in_the_session(monkeypatch):
    monkeypatch.setattr("cinemate.db.enrich.BATCH_SIZE", 3)
    session = _session(_movies(10))
    sizes = []
    real = type(session).expunge_all

    def spy(self):
        sizes.append(len(self.identity_map))
        return real(self)

    monkeypatch.setattr(type(session), "expunge_all", spy)
    stats = enrich_movies(session, FakeClient(), workers=1)
    assert stats.enriched == 10
    assert max(sizes) <= 3 + 0  # only the movies of the current batch were loaded
    assert len(session.identity_map) == 0
    assert session.scalar(select(Movie).where(Movie.tmdb_fetched_at.is_(None))) is None


def test_missing_features_rated_first_and_limit(monkeypatch):
    monkeypatch.setattr("cinemate.db.enrich.BATCH_SIZE", 2)
    session = _session(_movies(6))
    session.add(User(id=1))
    session.flush()
    session.add_all(Rating(user_id=1, movie_id=i, value=1) for i in (5, 3))
    session.commit()
    client = FakeClient()
    enrich_movies(session, client, missing_features=True, workers=1)
    assert [i for _, i in client.requested] == [3, 5, 1, 2, 4, 6]
    client = FakeClient()
    session.execute(Movie.__table__.update().values(tmdb_vote_count=None))
    session.commit()
    stats = enrich_movies(session, client, missing_features=True, workers=1, limit=3)
    assert [i for _, i in client.requested] == [3, 5, 1]
    assert stats.enriched == 3


def test_default_order_new_first_then_oldest(monkeypatch):
    monkeypatch.setattr("cinemate.db.enrich.BATCH_SIZE", 2)
    old = NOW - timedelta(days=100)
    session = _session(
        [
            Movie(
                title="a", tmdb_type="movie", tmdb_id=1, tmdb_fetched_at=NOW - timedelta(days=40)
            ),
            _m(2, tmdb_fetched_at=old),
            _m(3),
            _m(4, tmdb_fetched_at=NOW),
            Movie(
                title="e", tmdb_type="movie", tmdb_id=5, tmdb_fetched_at=NOW - timedelta(days=60)
            ),
            _m(6),
        ]
    )
    client = FakeClient()
    enrich_movies(session, client, workers=1, catalog_stale_days=30)
    assert [i for _, i in client.requested] == [3, 6, 2, 5, 1]
    client = FakeClient()
    session.execute(Movie.__table__.update().values(tmdb_fetched_at=None))
    session.commit()
    enrich_movies(session, client, workers=1, limit=3)
    assert [i for _, i in client.requested] == [1, 2, 3]


def test_extended_order_and_pool(monkeypatch):
    monkeypatch.setattr("cinemate.db.enrich.BATCH_SIZE", 2)
    session = _session(
        [
            Movie(
                title="a", tmdb_type="movie", tmdb_id=1, details_fetched_at=NOW - timedelta(days=90)
            ),
            _m(2),
            Movie(
                title="c", tmdb_type="movie", tmdb_id=3, details_fetched_at=NOW - timedelta(days=50)
            ),
            _m(4),
        ]
    )
    session.add(User(id=1))
    session.flush()
    session.add_all(Rating(user_id=1, movie_id=i, value=1) for i in (1, 2, 3))
    session.commit()
    client = FakeClient()
    stats = enrich_movies(session, client, extended=True, workers=1)
    assert [i for _, i in client.requested] == [2, 1, 3]
    assert stats.enriched == 3


def test_progress_lines(monkeypatch):
    monkeypatch.setattr("cinemate.db.enrich.PROGRESS_EVERY", 4)
    monkeypatch.setattr("cinemate.db.enrich.BATCH_SIZE", 3)
    session = _session(_movies(10))
    session.add(User(id=1))
    session.flush()
    session.add(Rating(user_id=1, movie_id=1, value=1))
    session.commit()
    ticks = iter(range(0, 1000, 10))  # 10 seconds per clock call
    lines = []
    client = FakeClient({("movie", i): _details("movie", i) for i in range(1, 10)})  # 10 -> 404
    stats = enrich_movies(
        session,
        client,
        missing_features=True,
        workers=1,
        report=lines.append,
        clock=lambda: next(ticks),
    )
    assert (stats.enriched, stats.not_found) == (9, 1)
    assert lines[:2] == ["к обработке: 10", "из них с оценками: 1"]
    progress = [line for line in lines if line.startswith("processed")]
    assert [line.split(",")[0] for line in progress] == [
        "processed 4/10",
        "processed 8/10",
        "processed 10/10",
    ]
    assert all("/s" in line for line in progress)
    assert progress[0].endswith("(4 enriched, 0 not found, 0 failed)")
    assert progress[-1].endswith("(9 enriched, 1 not found, 0 failed)")
    assert "min left" in progress[0]


def test_keyboard_interrupt_keeps_done_and_rerun_continues(monkeypatch):
    monkeypatch.setattr("cinemate.db.enrich.BATCH_SIZE", 2)
    session = _session(_movies(5))
    with pytest.raises(KeyboardInterrupt):
        enrich_movies(session, FakeClient(interrupt_on=4), workers=1)
    session.rollback()  # what is not committed is lost: only committed data counts
    left = {
        m.tmdb_id for m in session.scalars(select(Movie).where(Movie.tmdb_fetched_at.is_(None)))
    }
    assert left == {4, 5}
    client = FakeClient()
    stats = enrich_movies(session, client, workers=1)
    assert sorted(i for _, i in client.requested) == [4, 5]
    assert stats.enriched == 2


def test_sync_changes_counts_failed_record(monkeypatch):
    import cinemate.db.sync_changes as module

    def apply(session, movie, details):
        raise DataError("INSERT", {}, Exception("x"))

    class Changes(FakeClient):
        def changes(self, tmdb_type, start, end):
            return [1, 2]

    monkeypatch.setattr(module, "apply_details", apply)
    session = _session([_m(1)])
    lines = []
    stats = sync_changes(session, Changes(), types=["movie"], workers=1, report=lines.append)
    assert (stats.updated, stats.added, stats.failed) == (0, 1, 1)
    assert lines == ["failed: movie id 1, TMDB movie 1: DataError"]


def test_movie_card_survives_write_error(monkeypatch):
    from fastapi.testclient import TestClient

    import cinemate.db.enrich as module

    def apply(session, movie, details):
        movie.title = "changed"
        raise DataError("INSERT", {}, Exception("too long"))

    monkeypatch.setattr(module, "apply_details", apply)
    app = create_app("sqlite:///:memory:", tmdb_client=FakeClient())
    with app.state.session_factory() as session:
        session.add(Movie(id=1, title="Kept", tmdb_type="movie", tmdb_id=10))
        session.commit()
    with TestClient(app) as client:
        assert client.post("/api/session").status_code in (200, 201)
        response = client.get("/api/movies/1")
    assert response.status_code == 200
    assert response.json()["title"] == "Kept"
