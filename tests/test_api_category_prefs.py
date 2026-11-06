import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemate.api.app import create_app
from cinemate.config import RecommenderSettings
from cinemate.db.features import seed_genres
from cinemate.db.models import Movie, Rating, User, UserCategoryPref
from tests.category_fixtures import CF, MARVEL, MARVEL_CANDIDATES, OTHER, seed


@pytest.fixture
def app():
    app = create_app("sqlite:///:memory:", recommender_settings=RecommenderSettings(**CF))
    seed_genres(app.state.engine)
    with app.state.session_factory() as session:
        seed(session, dislikes=0)
        # users 2..8 rated everything; user 1 is replaced by the session user below
        session.query(Rating).filter(Rating.user_id == 1).delete()
        session.commit()
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        user_id = client.post("/api/session").json()["user_id"]
        with app.state.session_factory() as session:
            for m in range(1, 7):
                session.add(Rating(user_id=user_id, movie_id=m, value=1))
            for m in MARVEL:
                session.add(Rating(user_id=user_id, movie_id=m, value=-1))
            for m in OTHER[:2]:
                session.add(Rating(user_id=user_id, movie_id=m, value=1))
            session.commit()
        yield client


def ids(client, limit=40):
    body = client.get(f"/api/recommendations?limit={limit}").json()
    assert body["strategy"] == "collaborative"
    return [i["movie"]["id"] for i in body["items"]]


def test_requires_session(app):
    with TestClient(app) as client:
        assert client.get("/api/category-prefs").status_code == 401
        body = {"kind": "studio", "key": "1", "show": True}
        assert client.post("/api/category-prefs", json=body).status_code == 401


def test_get_lists_triggered_categories_with_counts(client):
    views = {(v["kind"], v["key"]): v for v in client.get("/api/category-prefs").json()}
    assert views[("studio", "1")] == {
        "kind": "studio",
        "key": "1",
        "name": "Marvel Studios",
        "disliked": 5,
        "rated": 5,
        "show": False,
    }
    assert views[("genre", "28")]["name"] == "Action"
    ru = client.get("/api/category-prefs", headers={"Accept-Language": "ru"}).json()
    assert {v["name"] for v in ru if v["kind"] == "genre"} == {"боевик"}


def test_hidden_then_shown_then_hidden_again(client, app):
    def position_of_candidates():
        feed = ids(client)
        return [feed.index(m) for m in MARVEL_CANDIDATES]

    assert min(position_of_candidates()) >= len(OTHER) - 2  # after the other movies

    for kind, key in (("studio", "1"), ("genre", "28")):
        body = {"kind": kind, "key": key, "show": True}
        assert client.post("/api/category-prefs", json=body).json()["ok"] is True
    assert sorted(position_of_candidates()) == [0, 1, 2]
    shown = {(v["kind"], v["key"]): v["show"] for v in client.get("/api/category-prefs").json()}
    assert shown == {("studio", "1"): True, ("genre", "28"): True}
    with app.state.session_factory() as session:
        assert session.scalar(select(UserCategoryPref.mode)) == "show"

    for kind, key in (("studio", "1"), ("genre", "28")):
        client.post("/api/category-prefs", json={"kind": kind, "key": key, "show": False})
    assert min(position_of_candidates()) >= len(OTHER) - 2
    assert {v["show"] for v in client.get("/api/category-prefs").json()} == {False}


def test_rejects_unknown_kind_and_empty_key(client):
    for body in (
        {"kind": "actor", "key": "1", "show": True},
        {"kind": "studio", "key": "", "show": True},
        {"kind": "studio", "key": "1"},
    ):
        assert client.post("/api/category-prefs", json=body).status_code == 422


def test_control_variant_sees_no_triggered_categories_but_keeps_overrides(client, app):
    assert client.get("/api/category-prefs").json()  # rule on: categories triggered
    body = {"kind": "studio", "key": "1", "show": True}
    client.post("/api/category-prefs", json=body)
    app.state.recommender_settings = RecommenderSettings(**CF, ab_variants=("control",))
    views = client.get("/api/category-prefs").json()
    assert [(v["kind"], v["key"], v["show"]) for v in views] == [("studio", "1", True)]


def _rate_at(app, user_id, movie_id, value, minute):
    from datetime import UTC, datetime

    with app.state.session_factory() as session:
        rating = session.scalar(
            select(Rating).where(Rating.user_id == user_id, Rating.movie_id == movie_id)
        )
        if rating is None:
            rating = Rating(user_id=user_id, movie_id=movie_id, value=value)
            session.add(rating)
        rating.value = value
        rating.created_at = datetime(2026, 1, 1, 12, minute, tzinfo=UTC)
        session.commit()


def _movies(client, kind, key, **kwargs):
    return client.get(f"/api/category-prefs/{kind}/{key}/movies", **kwargs)


def test_category_movies_requires_session(app):
    with TestClient(app) as anon:
        assert _movies(anon, "studio", "1").status_code == 401


def test_category_movies_dislikes_first_then_likes_newest_first(client, app):
    user_id = client.get("/api/me").json()["user_id"]
    for minute, movie_id in enumerate(MARVEL):
        _rate_at(app, user_id, movie_id, -1, minute)
    _rate_at(app, user_id, MARVEL_CANDIDATES[0], 1, 0)  # a like older than every dislike
    _rate_at(app, user_id, MARVEL_CANDIDATES[1], 1, 30)
    with app.state.session_factory() as session:
        movie = session.get(Movie, MARVEL[0])
        movie.title_ru = "Мстители"
        movie.year = 2012
        movie.poster_path = "/p.jpg"
        session.commit()

    for kind, key in (("studio", "1"), ("genre", "28")):
        body = _movies(client, kind, key).json()
        assert [(i["movie_id"], i["value"]) for i in body] == [
            *((m, -1) for m in reversed(MARVEL)),
            (MARVEL_CANDIDATES[1], 1),
            (MARVEL_CANDIDATES[0], 1),
        ]
    last = _movies(client, "studio", "1").json()[len(MARVEL) - 1]
    assert last == {
        "movie_id": MARVEL[0],
        "title": f"m{MARVEL[0]}",
        "title_ru": "Мстители",
        "year": 2012,
        "poster_path": "/p.jpg",
        "value": -1,
    }


def test_category_movies_only_rated_movies_of_the_category(client):
    # drama movies 1..6 and OTHER[:2] are liked but are not in the action genre / studio
    ids_ = {i["movie_id"] for i in _movies(client, "genre", "28").json()}
    assert ids_ == set(MARVEL)
    drama = _movies(client, "genre", "18").json()
    assert {i["movie_id"] for i in drama} == {*range(1, 7), *OTHER[:2]}
    assert {i["value"] for i in drama} == {1}


def test_category_movies_match_category_stats_counts(client):
    prefs = {(v["kind"], v["key"]): v for v in client.get("/api/category-prefs").json()}
    for (kind, key), view in prefs.items():
        items = _movies(client, kind, key).json()
        assert sum(i["value"] < 0 for i in items) == view["disliked"]
        assert len(items) == view["rated"]


def test_category_movies_studio_not_recognisable_when_too_big(client, app):
    app.state.recommender_settings = RecommenderSettings(**{**CF, "hide_studio_max_movies": 1})
    assert _movies(client, "studio", "1").json() == []
    assert len(_movies(client, "genre", "28").json()) == len(MARVEL)


def test_category_movies_unknown_category_is_404(client):
    for kind, key in (
        ("studio", "999"),
        ("genre", "999999"),
        ("collection", "5"),
        ("anime", "other"),
        ("actor", "1"),
        ("studio", "abc"),
    ):
        assert _movies(client, kind, key).status_code == 404, (kind, key)
    assert _movies(client, "anime", "anime").json() == []


def test_category_movies_limited_to_fifty(client, app):
    from cinemate.services.categories import CATEGORY_MOVIES_LIMIT, get_category_movies

    assert CATEGORY_MOVIES_LIMIT == 50
    with app.state.session_factory() as session:
        user = session.get(User, client.get("/api/me").json()["user_id"])
        store = app.state.matrix_store
        got = get_category_movies(session, store, user, "genre", "18", limit=3)
        assert len(got) == 3
