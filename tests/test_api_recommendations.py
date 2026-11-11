import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemate.api.app import create_app
from cinemate.api.schemas import MovieCard, MovieDetail
from cinemate.config import RecommenderSettings
from cinemate.db.models import Event, Movie, Rating, User


@pytest.fixture
def app():
    app = create_app(
        "sqlite:///:memory:", recommender_settings=RecommenderSettings(min_user_ratings=5)
    )
    with app.state.session_factory() as session:
        session.add_all(
            [
                Movie(
                    id=i,
                    title=f"M{i}",
                    original_title=f"O{i}",
                    title_ru="Ру7" if i == 7 else None,
                    year=2000 + i,
                )
                for i in range(1, 9)
            ]
        )
        for _ in range(6):
            user = User(is_synthetic=True)
            session.add(user)
            session.flush()
            for movie_id in range(1, 8):
                session.add(Rating(user_id=user.id, movie_id=movie_id, value=1))
        session.commit()
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.post("/api/session")
        yield client


def _events(app):
    with app.state.session_factory() as session:
        return list(session.scalars(select(Event)))


def test_requires_session(app):
    with TestClient(app) as client:
        assert client.get("/api/recommendations").status_code == 401
        assert client.get("/api/movies/1").status_code == 401


def test_fallback_for_new_user(app, client):
    body = client.get("/api/recommendations?limit=5").json()
    assert body["strategy"] == "fallback"
    assert 0 < len(body["items"]) <= 5
    assert all(i["liked_by"] == 0 and i["because_of"] == [] for i in body["items"])
    events = _events(app)
    assert len(events) == len(body["items"])
    assert {e.session_id for e in events} == {body["session_id"]}
    assert {e.type for e in events} == {"impression"}
    assert {e.strategy for e in events} == {"fallback"}


def test_collaborative_with_neighbors(app, client):
    for movie_id in range(1, 7):
        assert (
            client.post("/api/ratings", json={"movie_id": movie_id, "value": 1}).status_code == 200
        )
    body = client.get("/api/recommendations").json()
    assert body["strategy"] == "collaborative"
    assert [i["movie"]["id"] for i in body["items"]] == [7]
    item = body["items"][0]
    assert item["liked_by"] > 0
    assert item["because_of"]
    assert item["twin"] is None or set(item["twin"]) == {"common", "of"}
    assert item["movie"]["original_title"] == "O7"
    assert item["movie"]["title_ru"] == "Ру7"
    assert all(b["title_ru"] is None for b in item["because_of"])
    assert {e.strategy for e in _events(app)} == {"collaborative"}


def test_each_call_new_session_id(client):
    first = client.get("/api/recommendations").json()["session_id"]
    second = client.get("/api/recommendations").json()["session_id"]
    assert first != second


@pytest.mark.parametrize("limit", [0, 51, -1])
def test_limit_out_of_range(client, limit):
    assert client.get(f"/api/recommendations?limit={limit}").status_code == 422


def test_movie_detail(client):
    body = client.get("/api/movies/3").json()
    assert body["title"] == "M3"
    assert body["title_ru"] is None
    assert body["year"] == 2003
    assert set(MovieCard.model_fields) <= set(body)
    assert set(body) - set(MovieCard.model_fields) == set(MovieDetail.model_fields) - set(
        MovieCard.model_fields
    )
    assert {
        "id",
        "title",
        "title_ru",
        "original_title",
        "year",
        "overview",
        "poster_path",
        "genres",
        "runtime",
    } <= set(body)


def test_movie_not_found(client):
    assert client.get("/api/movies/999").status_code == 404


def test_app_settings_from_env(monkeypatch):
    monkeypatch.setenv("REC_LAMBDA", "12")
    app = create_app("sqlite:///:memory:")
    assert app.state.recommender_settings.lam == 12.0


def test_argument_overrides_env(monkeypatch):
    monkeypatch.setenv("REC_LAMBDA", "12")
    app = create_app("sqlite:///:memory:", recommender_settings=RecommenderSettings(lam=1.0))
    assert app.state.recommender_settings.lam == 1.0


def test_invalid_env_stops_app(monkeypatch):
    monkeypatch.setenv("REC_K", "0")
    with pytest.raises(ValueError, match="REC_K"):
        create_app("sqlite:///:memory:")


def test_route_passes_settings(monkeypatch):
    from cinemate.api import routes

    seen = {}
    real = routes.get_recommendations

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(routes, "get_recommendations", spy)
    settings = RecommenderSettings(lam=3.0)
    app = create_app("sqlite:///:memory:", recommender_settings=settings)
    with TestClient(app) as client:
        client.post("/api/session")
        assert client.get("/api/recommendations").status_code == 200
    assert seen["settings"] is settings


def test_because_taste_in_the_request_language(app, client):
    from cinemate.db.features import seed_genres
    from cinemate.db.models import MovieGenre

    seed_genres(app.state.engine)
    with app.state.session_factory() as session:
        session.add_all([MovieGenre(movie_id=i, genre_id=14) for i in range(1, 9)])
        session.commit()
    for movie_id in range(1, 7):
        client.post("/api/ratings", json={"movie_id": movie_id, "value": 1})
    en = client.get("/api/recommendations", headers={"Accept-Language": "en"}).json()
    ru = client.get("/api/recommendations", headers={"Accept-Language": "ru"}).json()
    assert en["items"][0]["because_taste"] == {"kind": "genre", "id": "14", "name": "Fantasy"}
    assert ru["items"][0]["because_taste"]["name"] == "фэнтези"


def test_no_because_taste_without_a_sure_feature(client):
    for movie_id in range(1, 7):
        client.post("/api/ratings", json={"movie_id": movie_id, "value": 1})
    items = client.get("/api/recommendations").json()["items"]
    assert items and all(i["because_taste"] is None for i in items)


def test_collection_card_for_a_franchise(app, client):
    from cinemate.db.models import Collection

    with app.state.session_factory() as session:
        session.add(Collection(id=5, name="Saga"))
        session.flush()
        for movie_id in (7, 8):
            session.get(Movie, movie_id).collection_id = 5
        session.commit()
    for movie_id in range(1, 7):
        client.post("/api/ratings", json={"movie_id": movie_id, "value": 1})
    (item,) = client.get("/api/recommendations").json()["items"]
    assert item["movie"]["id"] == 7
    assert item["collection"] == {
        "id": 5,
        "name": "Saga",
        "parts": 2,
        "unseen": 2,
        "mode": "first",
        "rated_parts": [],
    }


def test_collection_is_null_without_a_franchise(client):
    for movie_id in range(1, 7):
        client.post("/api/ratings", json={"movie_id": movie_id, "value": 1})
    items = client.get("/api/recommendations").json()["items"]
    assert items and all(i["collection"] is None for i in items)


@pytest.fixture
def feed_app():
    """Fifty movies; a user with nothing rated gets the fallback feed of all of them."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        session.add_all(
            [Movie(id=i, title=f"M{i}", original_title=f"O{i}", year=2000) for i in range(1, 51)]
        )
        for _ in range(3):
            user = User(is_synthetic=True)
            session.add(user)
            session.flush()
            for movie_id in range(1, 51):
                session.add(Rating(user_id=user.id, movie_id=movie_id, value=1))
        session.commit()
    return app


@pytest.fixture
def feed_client(feed_app):
    with TestClient(feed_app) as client:
        client.post("/api/session")
        yield client


def _ids(body):
    return [i["movie"]["id"] for i in body["items"]]


def test_pages_in_one_session_do_not_overlap(feed_app, feed_client):
    first = feed_client.get("/api/recommendations?limit=20").json()
    assert len(first["items"]) == 20
    assert first["next_offset"] == 20
    assert first["has_more"] is True
    sid = first["session_id"]
    second = feed_client.get(f"/api/recommendations?session_id={sid}&offset=20&limit=20").json()
    third = feed_client.get(
        f"/api/recommendations?session_id={sid}&offset={second['next_offset']}&limit=20"
    ).json()
    assert second["session_id"] == third["session_id"] == sid
    all_ids = _ids(first) + _ids(second) + _ids(third)
    assert len(all_ids) == len(set(all_ids)) == 50
    assert third["has_more"] is False
    assert {e.session_id for e in _events(feed_app)} == {sid}
    assert len(_events(feed_app)) == 50


def test_skips_movies_rated_after_the_snapshot(feed_client):
    first = feed_client.get("/api/recommendations?limit=10").json()
    sid = first["session_id"]
    upcoming = feed_client.get(f"/api/recommendations?session_id={sid}&offset=10&limit=5").json()
    reacted = _ids(upcoming)[:2]
    feed_client.post("/api/ratings", json={"movie_id": reacted[0], "value": 1})
    feed_client.post("/api/seen", json={"movie_id": reacted[1], "type": "watched"})
    again = feed_client.get(
        f"/api/recommendations?session_id={sid}&offset={first['next_offset']}&limit=5"
    ).json()
    assert not set(reacted) & set(_ids(again))
    assert len(again["items"]) == 5


def test_recovers_after_losing_the_snapshot_without_repeats(feed_app, feed_client):
    first = feed_client.get("/api/recommendations?limit=20").json()
    sid = first["session_id"]
    feed_app.state.feed_cache = type(feed_app.state.feed_cache)()  # as after a restart
    again = feed_client.get(f"/api/recommendations?session_id={sid}&offset=20&limit=20").json()
    assert again["session_id"] == sid
    assert again["items"]
    assert not set(_ids(first)) & set(_ids(again))
    assert {e.session_id for e in _events(feed_app)} == {sid}


def test_foreign_session_is_not_found(feed_app, feed_client):
    sid = feed_client.get("/api/recommendations?limit=5").json()["session_id"]
    with TestClient(feed_app) as other:
        other.post("/api/session")
        assert other.get(f"/api/recommendations?session_id={sid}").status_code == 404
        feed_app.state.feed_cache = type(feed_app.state.feed_cache)()
        assert other.get(f"/api/recommendations?session_id={sid}").status_code == 404


def test_exhausted_feed_has_no_more(feed_client):
    body = feed_client.get("/api/recommendations?limit=50").json()
    assert body["has_more"] is False
    assert body["next_offset"] == len(body["items"])
