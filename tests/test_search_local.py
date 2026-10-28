import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cinemate.api.app import create_app
from cinemate.db.models import Movie, Rating
from cinemate.db.session import create_all, make_engine
from cinemate.services.search import (
    SearchSelector,
    normalize_query,
    resolve_search_source,
    search_local,
)
from cinemate.tmdb import TmdbError, TmdbSearchItem


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with Session(engine) as s:
        yield s


def add(session, tmdb_id, title, pop=None, **kw):
    m = Movie(
        tmdb_type=kw.pop("tmdb_type", "movie"),
        tmdb_id=tmdb_id,
        title=title,
        tmdb_popularity=pop,
        genres=[],
        **kw,
    )
    session.add(m)
    session.flush()
    return m


def ids(results):
    return [r.item.tmdb_id for r in results]


def test_normalize_query():
    assert normalize_query("  Ёлки,   НОВЫЕ!! ") == "елки новые"
    assert normalize_query("Spider-Man: Home_coming") == "spider man home coming"
    assert normalize_query("?!") == ""


def test_yo_and_case_are_folded_both_ways(session):
    add(session, 1, "Ёлка", title_ru="Ёлки")
    add(session, 2, "Other")
    assert ids(search_local(session, "ЕЛКА")) == [1]
    assert ids(search_local(session, "ёлка")) == [1]


def test_matches_title_ru_and_original_title(session):
    add(session, 1, "Dune", title_ru="Дюна", original_title="Dune: Part One")
    assert ids(search_local(session, "дюна")) == [1]
    assert ids(search_local(session, "part one")) == [1]
    assert ids(search_local(session, "nothing")) == []
    assert search_local(session, "дюна", language="ru-RU")[0].item.title == "Дюна"
    assert search_local(session, "дюна", language="en-US")[0].item.title == "Dune"


def test_punctuation_in_title_matches_by_words(session):
    add(session, 1, "Spider-Man")
    assert ids(search_local(session, "spider man")) == [1]


def test_punctuated_titles_rank_as_exact_and_prefix(session):
    add(session, 1, "Spider Man 2", pop=99)
    add(session, 2, "Spider-Man", pop=1)
    add(session, 3, "Mission: Impossible", pop=5)
    add(session, 4, "Mission Impossible Fallout", pop=50)
    assert ids(search_local(session, "spider-man")) == [2, 1]
    assert ids(search_local(session, "mission impossible")) == [3, 4]


def test_order_exact_prefix_rest_then_popularity(session):
    add(session, 1, "The Matrix Reloaded", pop=90)  # contains
    add(session, 2, "Matrix Revolutions", pop=10)  # prefix, low popularity
    add(session, 3, "Matrix Resurrections", pop=50)  # prefix, higher popularity
    add(session, 4, "Matrix", pop=1)  # exact
    add(session, 5, "Reloaded matrix", pop=None)  # contains, no popularity
    assert ids(search_local(session, "matrix")) == [4, 3, 2, 1, 5]


def test_requires_tmdb_pair_and_sets_movie_id_and_user_value(session):
    add(session, 1, "Alien")
    session.add(Movie(title="Alien local", genres=[]))
    session.flush()
    from cinemate.db.models import User

    user = User(pool="world")
    session.add(user)
    session.flush()
    movie = session.query(Movie).filter_by(tmdb_id=1).one()
    session.add(Rating(user_id=user.id, movie_id=movie.id, value=-1))
    session.flush()
    [r] = search_local(session, "alien", user=user)
    assert (r.movie_id, r.user_value) == (movie.id, -1)


def test_pagination(session):
    for i in range(1, 6):
        add(session, i, f"Film {i}", pop=100 - i)
    assert ids(search_local(session, "film", 1, page_size=2)) == [1, 2]
    assert ids(search_local(session, "film", 2, page_size=2)) == [3, 4]
    assert ids(search_local(session, "film", 3, page_size=2)) == [5]
    assert search_local(session, "film", 4, page_size=2) == []


def test_symbols_in_query_are_dropped_not_treated_as_wildcards(session):
    add(session, 1, "100% Wolf")
    add(session, 2, "Wolf")
    assert ids(search_local(session, "100%")) == [1]
    assert ids(search_local(session, "_wxlf_")) == []


def test_resolve_search_source():
    assert resolve_search_source(None, {}) == "auto"
    assert resolve_search_source(None, {"SEARCH_SOURCE": " Local "}) == "local"
    assert resolve_search_source("tmdb", {"SEARCH_SOURCE": "local"}) == "tmdb"
    with pytest.raises(ValueError, match="SEARCH_SOURCE"):
        resolve_search_source(None, {"SEARCH_SOURCE": "bing"})


def test_selector_threshold_and_hourly_recheck():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(engine, expire_on_commit=False)
    now = [0.0]
    sel = SearchSelector("auto", factory, threshold=2, ttl=3600, clock=lambda: now[0])
    assert sel.refresh() is False
    with factory() as s:
        add(s, 1, "A")
        add(s, 2, "B")
        s.commit()
    assert sel.catalog_ready() is False  # cached: no query per search
    now[0] = 3601
    assert sel.catalog_ready() is True


class FakeTmdb:
    def __init__(self, fail=False):
        self.searches = []
        self.fail = fail

    def search(self, query, language, page=1):
        self.searches.append(query)
        if self.fail:
            raise TmdbError("TMDB returned HTTP 500")
        return [TmdbSearchItem("movie", 999, "Remote", None, None, None)]


def make_client(source, tmdb, threshold=1, seed=True):
    app = create_app(
        "sqlite:///:memory:",
        tmdb_client=tmdb,
        search_source=source,
        search_local_threshold=threshold,
    )
    if seed:
        with app.state.session_factory() as s:
            add(s, 1, "Local Film", pop=5)
            s.commit()
        app.state.search_selector.refresh()
    client = TestClient(app)
    client.post("/api/session")
    return client


def test_auto_uses_local_without_touching_tmdb():
    tmdb = FakeTmdb()
    c = make_client("auto", tmdb)
    body = c.get("/api/search", params={"q": "local"}).json()
    assert [r["tmdb_id"] for r in body] == [1] and body[0]["movie_id"] is not None
    assert tmdb.searches == []


def test_auto_falls_back_to_tmdb_when_local_is_empty():
    tmdb = FakeTmdb()
    c = make_client("auto", tmdb)
    body = c.get("/api/search", params={"q": "nothing here"}).json()
    assert [r["tmdb_id"] for r in body] == [999]
    assert body[0]["movie_id"] is None
    assert len(tmdb.searches) == 1
    # page 2 of an empty local result does not mix in unrelated TMDB results
    assert c.get("/api/search", params={"q": "nothing here", "page": 2}).json() == []


def test_auto_fallback_ignores_tmdb_failure():
    c = make_client("auto", FakeTmdb(fail=True))
    assert c.get("/api/search", params={"q": "nothing here"}).json() == []


def test_auto_below_threshold_uses_tmdb():
    tmdb = FakeTmdb()
    c = make_client("auto", tmdb, threshold=100)
    assert [r["tmdb_id"] for r in c.get("/api/search", params={"q": "local"}).json()] == [999]


def test_auto_below_threshold_without_key_uses_local():
    c = make_client("auto", None, threshold=100)
    assert [r["tmdb_id"] for r in c.get("/api/search", params={"q": "local"}).json()] == [1]


def test_local_mode_never_calls_tmdb_and_works_without_key():
    tmdb = FakeTmdb()
    c = make_client("local", tmdb, threshold=100)
    assert c.get("/api/search", params={"q": "nothing here"}).json() == []
    assert tmdb.searches == []
    assert make_client("local", None).get("/api/search", params={"q": "local"}).status_code == 200


def test_tmdb_mode_as_before():
    tmdb = FakeTmdb()
    c = make_client("tmdb", tmdb)
    assert [r["tmdb_id"] for r in c.get("/api/search", params={"q": "local"}).json()] == [999]
    assert make_client("tmdb", None).get("/api/search", params={"q": "local"}).status_code == 503
    assert (
        make_client("tmdb", FakeTmdb(fail=True))
        .get("/api/search", params={"q": "local"})
        .status_code
        == 502
    )


def test_search_source_from_env(monkeypatch):
    monkeypatch.setenv("SEARCH_SOURCE", "local")
    assert create_app("sqlite:///:memory:").state.search_selector.mode == "local"
    monkeypatch.setenv("SEARCH_SOURCE", "x")
    with pytest.raises(ValueError):
        create_app("sqlite:///:memory:")
