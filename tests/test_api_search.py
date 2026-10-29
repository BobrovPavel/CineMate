import pytest
from fastapi.testclient import TestClient

from cinemate.api.app import create_app
from cinemate.db.models import Movie, Rating
from cinemate.tmdb import TmdbDetails, TmdbError, TmdbSearchItem


class FakeTmdb:
    def __init__(self):
        self.searches = []
        self.fetches = 0
        self.fail = False

    def search(self, query, language, page=1):
        self.searches.append((query, language, page))
        if self.fail:
            raise TmdbError("TMDB returned HTTP 500")
        return [
            TmdbSearchItem("movie", 10, "Leviathan", "Левиафан", 2014, "/l.jpg"),
            TmdbSearchItem("tv", 10, "Show", None, None, None),
        ]

    def fetch_details(self, tmdb_type, tmdb_id):
        self.fetches += 1
        if tmdb_id == 404:
            return None
        if self.fail:
            raise TmdbError("TMDB returned HTTP 500")
        return TmdbDetails(
            tmdb_type=tmdb_type,
            tmdb_id=tmdb_id,
            title="Leviathan",
            original_title="Левиафан",
            year=2014,
            poster_path="/l.jpg",
            runtime=140,
            genres=["Drama"],
            imdb_id="tt2802154",
            title_ru="Левиафан",
            overview_ru="Описание",
        )


@pytest.fixture
def tmdb():
    return FakeTmdb()


@pytest.fixture
def app(tmdb):
    return create_app("sqlite:///:memory:", tmdb_client=tmdb)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.post("/api/session")
        yield client


def test_search_requires_session(app):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/search", params={"q": "leviathan"}).status_code == 401


@pytest.mark.parametrize("q", ["", "a", " ", "x" * 101])
def test_search_validates_q(client, q):
    assert client.get("/api/search", params={"q": q}).status_code == 422


def test_search_without_key_is_503(monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    with TestClient(create_app("sqlite:///:memory:", search_source="tmdb")) as c:
        c.post("/api/session")
        response = c.get("/api/search", params={"q": "leviathan"})
        assert response.status_code == 503
        assert "TMDB_API_KEY" in response.json()["detail"]
        assert (
            c.post("/api/movies/resolve", json={"tmdb_type": "movie", "tmdb_id": 1}).status_code
            == 503
        )


def test_search_results_language_and_shape(client, tmdb):
    response = client.get(
        "/api/search", params={"q": "leviathan"}, headers={"Accept-Language": "ru-RU,ru;q=0.9"}
    )
    assert response.status_code == 200
    assert tmdb.searches == [("leviathan", "ru-RU", 1)]
    assert response.json()[0] == {
        "tmdb_type": "movie",
        "tmdb_id": 10,
        "title": "Leviathan",
        "original_title": "Левиафан",
        "year": 2014,
        "poster_path": "/l.jpg",
        "movie_id": None,
        "user_value": None,
    }
    client.get("/api/search", params={"q": "other"}, headers={"Accept-Language": "en-US"})
    assert tmdb.searches[-1][1] == "en-US"


def test_search_marks_catalog_movie_and_rating_by_type(client, app):
    with app.state.session_factory() as s:
        movie = Movie(title="L", tmdb_type="movie", tmdb_id=10)
        s.add(movie)
        s.commit()
        movie_id = movie.id
    assert client.post("/api/ratings", json={"movie_id": movie_id, "value": -1}).status_code == 200
    first, second = client.get("/api/search", params={"q": "leviathan"}).json()
    assert (first["movie_id"], first["user_value"]) == (movie_id, -1)
    # same tmdb_id but another type is another work
    assert (second["movie_id"], second["user_value"]) == (None, None)


def test_search_is_cached(client, tmdb):
    for q in ("leviathan", "Leviathan ", "leviathan"):
        assert client.get("/api/search", params={"q": q}).status_code == 200
    assert len(tmdb.searches) == 1
    client.get("/api/search", params={"q": "leviathan", "page": 2})
    assert len(tmdb.searches) == 2


def test_search_tmdb_error_is_502_and_not_cached(client, tmdb):
    tmdb.fail = True
    assert client.get("/api/search", params={"q": "leviathan"}).status_code == 502
    tmdb.fail = False
    assert client.get("/api/search", params={"q": "leviathan"}).status_code == 200


def test_resolve_creates_movie_once_then_rating_works(client, app, tmdb):
    body = {"tmdb_type": "movie", "tmdb_id": 10}
    first = client.post("/api/movies/resolve", json=body)
    second = client.post("/api/movies/resolve", json=body)
    assert first.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["title"] == "Leviathan"
    assert first.json()["overview"] == "Описание"
    assert tmdb.fetches == 1
    movie_id = first.json()["id"]
    assert client.post("/api/ratings", json={"movie_id": movie_id, "value": 1}).json()["ok"]
    assert [i["movie_id"] for i in client.get("/api/profile").json()] == [movie_id]
    with app.state.session_factory() as s:
        assert s.query(Rating).count() == 1
    assert client.get("/api/search", params={"q": "leviathan"}).json()[0]["user_value"] == 1


def test_resolve_errors(client, tmdb):
    assert (
        client.post("/api/movies/resolve", json={"tmdb_type": "movie", "tmdb_id": 404}).status_code
        == 404
    )
    assert (
        client.post("/api/movies/resolve", json={"tmdb_type": "person", "tmdb_id": 1}).status_code
        == 422
    )
    assert (
        client.post("/api/movies/resolve", json={"tmdb_type": "movie", "tmdb_id": 0}).status_code
        == 422
    )
    tmdb.fail = True
    assert (
        client.post("/api/movies/resolve", json={"tmdb_type": "tv", "tmdb_id": 5}).status_code
        == 502
    )


def test_resolve_requires_session(app):
    with TestClient(app) as anonymous:
        response = anonymous.post("/api/movies/resolve", json={"tmdb_type": "movie", "tmdb_id": 1})
        assert response.status_code == 401


@pytest.mark.parametrize(
    ("cookie", "header", "language"),
    [("en", "ru-RU,ru;q=0.9", "en-US"), ("ru", "en-US", "ru-RU"), ("xx", "ru", "ru-RU")],
)
def test_search_language_follows_cookie(client, tmdb, cookie, header, language):
    client.cookies.set("cinemate_lang", cookie)
    client.get("/api/search", params={"q": "leviathan"}, headers={"Accept-Language": header})
    assert tmdb.searches == [("leviathan", language, 1)]
