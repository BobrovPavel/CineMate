import http.client
import json
import threading

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cinemate.db.enrich import enrich_movies
from cinemate.db.models import Movie
from cinemate.db.session import create_all, make_engine
from cinemate.db.sync_catalog import sync_catalog
from cinemate.tmdb import (
    PersistentTransport,
    TmdbClient,
    TmdbDetails,
    TmdbError,
    TmdbRateLimited,
    fetch_many,
)

KEY = "secret-key-123"


def _details(tmdb_type, tmdb_id):
    return TmdbDetails(tmdb_type, tmdb_id, f"{tmdb_type}{tmdb_id}", None, 2000, None, None)


class GatedClient(TmdbClient):
    """``fetch_details`` blocks until ``n`` requests are in flight at once."""

    def __init__(self, n, missing=()):
        self.n = n
        self.missing = set(missing)
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.threads = set()
        self.reached = threading.Event()

    def fetch_details(self, tmdb_type, tmdb_id):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.threads.add(threading.current_thread())
            if self.active >= self.n:
                self.reached.set()
        try:
            if not self.reached.wait(5):
                raise TmdbError("requests did not overlap")
        finally:
            with self.lock:
                self.active -= 1
        return None if (tmdb_type, tmdb_id) in self.missing else _details(tmdb_type, tmdb_id)


def test_requests_run_in_parallel():
    client = GatedClient(4)
    results = dict(fetch_many(client, [("movie", i) for i in range(8)], workers=4))
    assert client.peak == 4
    assert set(results) == {("movie", i) for i in range(8)}
    assert threading.current_thread() not in client.threads


def test_results_do_not_depend_on_completion_order():
    release = {i: threading.Event() for i in range(4)}

    class Ordered(TmdbClient):
        def __init__(self):
            pass

        def fetch_details(self, tmdb_type, tmdb_id):
            release[tmdb_id].wait(5)
            if tmdb_id > 0:
                release[tmdb_id - 1].set()  # finish in reverse order
            return _details(tmdb_type, tmdb_id)

    release[3].set()
    results = list(fetch_many(Ordered(), [("movie", i) for i in range(4)], workers=4))
    assert sorted((pair, d.title) for pair, d in results) == [
        (("movie", i), f"movie{i}") for i in range(4)
    ]


def test_at_most_twice_the_workers_are_submitted_ahead():
    taken = []

    def items():
        for i in range(50):
            taken.append(i)
            yield ("movie", i)

    gate = threading.Event()

    class Slow(TmdbClient):
        def __init__(self):
            pass

        def fetch_details(self, tmdb_type, tmdb_id):
            gate.wait(5)
            return None

    stream = fetch_many(Slow(), items(), workers=2)
    timer = threading.Timer(0.3, gate.set)
    timer.start()
    next(stream)
    assert len(taken) <= 2 * 2 + 1
    stream.close()
    timer.cancel()


def test_workers_one_runs_in_calling_thread_in_order():
    seen = []

    class Seq(TmdbClient):
        def __init__(self):
            pass

        def fetch_details(self, tmdb_type, tmdb_id):
            seen.append((tmdb_id, threading.current_thread()))
            return None

    list(fetch_many(Seq(), [("movie", 3), ("movie", 1)], workers=1))
    assert [i for i, _ in seen] == [3, 1]
    assert {t for _, t in seen} == {threading.current_thread()}


def test_error_yields_finished_results_then_raises():
    class Failing(TmdbClient):
        def __init__(self):
            pass

        def fetch_details(self, tmdb_type, tmdb_id):
            if tmdb_id == 1:
                raise TmdbError("boom")
            return _details(tmdb_type, tmdb_id)

    got = []
    with pytest.raises(TmdbError, match="boom"):
        for pair, _ in fetch_many(Failing(), [("movie", i) for i in range(40)], workers=3):
            got.append(pair)
    assert ("movie", 1) not in got
    assert len(got) < 39  # nothing new was sent after the failure


def test_invalid_workers():
    with pytest.raises(ValueError):
        list(fetch_many(GatedClient(1), [], workers=0))


# --- database writes stay in the main thread ---


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return sessionmaker(engine)


def test_sync_catalog_writes_only_from_main_thread(factory, tmp_path):
    import gzip

    from cinemate.db.sync_catalog import export_name

    day = __import__("datetime").date(2026, 10, 27)
    records = [
        {"id": i, "popularity": 5.0 + i, "video": False, "adult": False} for i in range(1, 31)
    ]
    body = gzip.compress("\n".join(json.dumps(r) for r in records).encode())
    (tmp_path / export_name("movie", day)).write_bytes(body)
    writers = set()

    with factory() as session:
        from sqlalchemy import event

        event.listen(
            session.get_bind(), "before_cursor_execute",
            lambda *a: writers.add(threading.current_thread()),
        )  # fmt: skip
        client = GatedClient(4, missing={("movie", 7)})
        stats = sync_catalog(
            session, client, types=["movie"], day=day, export_dir=tmp_path, workers=4
        )
        assert stats.added == 29 and stats.not_found == 1
        assert client.peak == 4
        assert writers == {threading.current_thread()}
        assert session.scalar(select(Movie.tmdb_popularity).where(Movie.tmdb_id == 30)) == 35.0


def test_enrich_parallel_updates_all(factory):
    with factory() as session:
        session.add_all(Movie(title=f"m{i}", tmdb_type="movie", tmdb_id=i) for i in range(1, 13))
        session.commit()
        client = GatedClient(3, missing={("movie", 5)})
        stats = enrich_movies(session, client, workers=3)
        assert (stats.enriched, stats.not_found) == (11, 1)
        assert client.peak == 3
        assert session.scalar(select(Movie.title).where(Movie.tmdb_id == 9)) == "movie9"


def test_keyboard_interrupt_in_worker_keeps_received(factory):
    class Interrupt(TmdbClient):
        def __init__(self):
            pass

        def fetch_details(self, tmdb_type, tmdb_id):
            if tmdb_id == 9:
                raise KeyboardInterrupt
            return _details(tmdb_type, tmdb_id)

    with factory() as session:
        session.add_all(Movie(title=f"m{i}", tmdb_type="movie", tmdb_id=i) for i in range(1, 11))
        session.commit()
        with pytest.raises(KeyboardInterrupt):
            enrich_movies(session, Interrupt(), workers=2)
    with factory() as other:
        done = other.scalars(select(Movie).where(Movie.tmdb_fetched_at.is_not(None))).all()
        assert done and 9 not in {m.tmdb_id for m in done}


# --- 429 shared by all threads ---


def test_429_in_one_thread_delays_the_others():
    sleeps = []
    now = [0.0]
    calls = []

    def http_get(url):
        calls.append(url)
        if len(calls) == 1:
            raise TmdbRateLimited(7.0)
        return 200, b'{"results": []}'

    client = TmdbClient(
        KEY, http_get=http_get, clock=lambda: now[0], sleep=sleeps.append, max_consecutive_429=5
    )
    client.search("a", "en")  # the 429 and its retry
    assert max(sleeps) == 7.0
    sleeps.clear()
    client.search("b", "en")  # another "thread": the limiter is still shifted
    assert sleeps and sleeps[0] > 6.0


def test_five_429_in_a_row_stop_with_a_clear_message():
    client = TmdbClient(
        KEY,
        http_get=lambda url: (429, b""),
        clock=lambda: 0.0,
        sleep=lambda s: None,
        max_consecutive_429=5,
    )
    calls = []
    original = client._http_get
    client._http_get = lambda url: (calls.append(1), original(url))[1]
    with pytest.raises(TmdbRateLimited) as exc:
        client.search("a", "en")
    assert len(calls) == 5
    assert "progress is saved" in str(exc.value) and KEY not in str(exc.value)


def test_success_resets_the_429_streak():
    answers = iter([(429, b"")] * 2 + [(200, b'{"results": []}')] + [(429, b"")] * 2)
    answers = list(answers) + [(200, b'{"results": []}')]
    it = iter(answers)
    client = TmdbClient(
        KEY,
        http_get=lambda url: next(it),
        clock=lambda: 0.0,
        sleep=lambda s: None,
        max_consecutive_429=3,
    )
    client.search("a", "en")
    client.search("b", "en")


def test_requests_per_second_sets_the_spacing():
    now = [0.0]
    sleeps = []
    client = TmdbClient(
        KEY,
        http_get=lambda url: (200, b'{"results": []}'),
        clock=lambda: now[0],
        sleep=sleeps.append,
        requests_per_second=10,
    )
    client.search("a", "en")
    client.search("b", "en")
    assert sleeps == [pytest.approx(0.1)]
    with pytest.raises(ValueError):
        TmdbClient(KEY, requests_per_second=0)


# --- persistent connections ---


class FakeResponse:
    def __init__(self, status=200, body=b"{}", headers=None, will_close=False):
        self.status = status
        self._body = body
        self._headers = headers or {}
        self.will_close = will_close

    def read(self):
        return self._body

    def getheader(self, name):
        return self._headers.get(name)


class FakeConnection:
    def __init__(self, plan, log):
        self.plan = plan  # list of responses or exceptions
        self.log = log
        self.closed = False

    def request(self, method, target):
        self.log.append(("request", target))

    def getresponse(self):
        item = self.plan.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def _transport(*plans):
    created = []
    plans = list(plans)

    def factory(host, timeout):
        conn = FakeConnection(plans.pop(0) if plans else [FakeResponse()], created)
        created.append(conn)
        return conn

    return PersistentTransport(factory), created


def test_connection_is_reused():
    transport, created = _transport([FakeResponse(), FakeResponse(), FakeResponse()])
    for _ in range(3):
        assert transport("https://api.themoviedb.org/3/x?api_key=k")[0] == 200
    assert len([c for c in created if isinstance(c, FakeConnection)]) == 1


def test_request_target_keeps_path_and_query():
    transport, log = _transport([FakeResponse()])
    transport("https://api.themoviedb.org/3/movie/1?api_key=k&language=en-US")
    assert ("request", "/3/movie/1?api_key=k&language=en-US") in log


def test_reconnects_after_a_broken_connection():
    transport, created = _transport(
        [FakeResponse(), http.client.RemoteDisconnected("gone")], [FakeResponse(body=b"ok")]
    )
    url = "https://api.themoviedb.org/3/x?api_key=k"
    transport(url)
    assert transport(url) == (200, b"ok")
    conns = [c for c in created if isinstance(c, FakeConnection)]
    assert len(conns) == 2 and conns[0].closed


def test_closed_by_server_is_reopened_next_time():
    transport, created = _transport([FakeResponse(will_close=True)], [FakeResponse()])
    url = "https://api.themoviedb.org/3/x?api_key=k"
    transport(url)
    transport(url)
    assert len([c for c in created if isinstance(c, FakeConnection)]) == 2


def test_each_thread_has_its_own_connection():
    transport, created = _transport([FakeResponse()], [FakeResponse()])
    url = "https://api.themoviedb.org/3/x?api_key=k"
    transport(url)
    thread = threading.Thread(target=transport, args=(url,))
    thread.start()
    thread.join()
    assert len([c for c in created if isinstance(c, FakeConnection)]) == 2


def test_persistent_failure_does_not_leak_key():
    boom = OSError(f"failed https://x/?api_key={KEY}")
    transport, _ = _transport([boom], [boom])
    client = TmdbClient(KEY, http_get=transport, clock=lambda: 0.0, sleep=lambda s: None)
    with pytest.raises(TmdbError) as exc:
        client.fetch_details("movie", 1)
    assert KEY not in str(exc.value) and KEY not in repr(exc.value.__cause__)


def test_429_status_raises_rate_limited_with_retry_after():
    transport, _ = _transport([FakeResponse(429, headers={"Retry-After": "4"})])
    with pytest.raises(TmdbRateLimited) as exc:
        transport("https://api.themoviedb.org/3/x?api_key=k")
    assert exc.value.retry_after == 4.0


# --- CLI ---


def test_cli_flags_are_validated(capsys):
    from cinemate.cli import main

    for flags in (["--workers", "0"], ["--workers", "17"], ["--rps", "36"], ["--rps", "0"]):
        with pytest.raises(SystemExit):
            main(["enrich-movies", *flags])
        with pytest.raises(SystemExit):
            main(["sync-catalog", *flags])
    capsys.readouterr()


def test_cli_passes_workers_and_rps(monkeypatch, tmp_path, capsys):
    from cinemate.cli import main

    made = {}

    class Recording(TmdbClient):
        def __init__(self, key, **kw):
            made.update(kw)

    monkeypatch.setenv("TMDB_API_KEY", "k")
    monkeypatch.setattr("cinemate.cli.TmdbClient", Recording)
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    assert main(["enrich-movies", "--database-url", url, "--workers", "3", "--rps", "30"]) == 0
    assert made == {"requests_per_second": 30.0, "max_consecutive_429": 5}
