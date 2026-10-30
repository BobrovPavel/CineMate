import pytest
from fastapi.testclient import TestClient

from cinemate.api.app import create_app
from cinemate.db.models import (
    Collection,
    Company,
    ExternalRating,
    Keyword,
    Movie,
    MovieCompany,
    MovieCredit,
    MovieKeyword,
    Person,
)


@pytest.fixture
def app():
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        session.add_all(
            [
                Movie(
                    id=1,
                    tmdb_type="movie",
                    tmdb_id=10,
                    title="Leviathan",
                    original_title="Левиафан",
                    title_ru="Левиафан (ру)",
                    year=2014,
                    overview="text",
                    poster_path="/p.jpg",
                    runtime=140,
                    certification="16+",
                    certification_country="RU",
                    budget=4_400_000,
                    revenue=0,
                    tagline="Truth",
                    countries=["RU"],
                    tmdb_vote_average=7.5,
                    tmdb_vote_count=100,
                    collection_id=5,
                ),
                Movie(
                    id=2,
                    tmdb_type="tv",
                    tmdb_id=20,
                    title="Show",
                    year=2020,
                    budget=5,
                    revenue=6,
                    number_of_seasons=3,
                    number_of_episodes=30,
                ),
                Movie(id=3, title="Bare"),
                Collection(id=5, name="Saga"),
                Company(id=1, name="Studio B"),
                Company(id=2, name="Studio A"),
                Person(id=1, name="Dir", profile_path=None),
                Person(id=2, name="Actor", profile_path="/a.jpg"),
                Person(id=3, name="Maker"),
                Keyword(id=1, name="epic"),
            ]
        )
        session.flush()
        session.add_all(
            [
                MovieCompany(movie_id=1, company_id=1),
                MovieCompany(movie_id=1, company_id=2),
                MovieKeyword(movie_id=1, keyword_id=1),
                MovieCredit(movie_id=1, person_id=1, role="director", ord=0),
                MovieCredit(movie_id=1, person_id=2, role="cast", character="Hero", ord=0),
                MovieCredit(movie_id=2, person_id=3, role="creator", ord=0),
                ExternalRating(movie_id=1, source="imdb", value=8.0, votes=5000),
            ]
        )
        session.commit()
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.post("/api/session")
        yield client


def test_movie_detail_full(client):
    body = client.get("/api/movies/1", headers={"Accept-Language": "ru"}).json()
    assert body["display_title"] == "Левиафан (ру)"
    assert body["second_title"] == "Левиафан"
    assert body["type"] == "movie"
    assert body["certification"] == "16+"
    assert body["budget"] == 4_400_000
    assert body["revenue"] is None
    assert body["tagline"] == "Truth"
    assert body["keywords"] == ["epic"]
    assert body["studios"] == ["Studio A", "Studio B"]
    assert body["countries"] == ["RU"]
    assert body["collection"] == "Saga"
    assert body["directors"] == [{"id": 1, "name": "Dir"}]
    assert body["cast"] == [
        {"id": 2, "name": "Actor", "character": "Hero", "profile_path": "/a.jpg"}
    ]
    assert [r["source"] for r in body["ratings"]] == ["tmdb", "imdb"]
    assert body["user_value"] is None
    assert body["user_mark"] is None


def test_titles_follow_language(client):
    body = client.get("/api/movies/1", headers={"Accept-Language": "en"}).json()
    assert body["display_title"] == "Leviathan"
    assert body["second_title"] == "Левиафан"


def test_tv_detail(client):
    body = client.get("/api/movies/2").json()
    assert body["type"] == "tv"
    assert body["number_of_seasons"] == 3
    assert body["number_of_episodes"] == 30
    assert body["budget"] is None
    assert body["revenue"] is None
    assert body["creators"] == [{"id": 3, "name": "Maker"}]


def test_empty_fields_do_not_break(client):
    body = client.get("/api/movies/3").json()
    assert body["display_title"] == "Bare"
    assert body["second_title"] is None
    assert body["type"] == "movie"
    for field in ("keywords", "studios", "countries", "cast", "ratings", "directors", "creators"):
        assert body[field] == []
    for field in ("collection", "certification", "tagline", "budget", "number_of_seasons"):
        assert body[field] is None


def test_user_reaction(client):
    client.post("/api/ratings", json={"movie_id": 1, "value": -1})
    client.post("/api/seen", json={"movie_id": 1, "type": "watched"})
    body = client.get("/api/movies/1").json()
    assert body["user_value"] == -1
    assert body["user_mark"] == "watched"


def test_not_found(client):
    assert client.get("/api/movies/999").status_code == 404
