from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemate.api.app import create_app
from cinemate.config import RecommenderSettings
from cinemate.db.models import Event, Movie, Rating, User
from cinemate.services.ab import assign_variant, settings_for_variant

AB = RecommenderSettings(ab_variants=("control", "taste"), min_user_ratings=5)


def test_assignment_is_stable_and_splits_users():
    first = [assign_variant(AB, uid) for uid in range(1, 201)]
    assert first == [assign_variant(AB, uid) for uid in range(1, 201)]
    assert set(first) == {"control", "taste"}
    assert 60 < first.count("control") < 140


def test_assignment_depends_on_variant_list():
    one = replace(AB, ab_variants=("taste",))
    assert {assign_variant(one, uid) for uid in range(1, 20)} == {"taste"}


def test_ab_off():
    settings = RecommenderSettings()
    assert assign_variant(settings, 1) is None
    assert settings_for_variant(settings, None) is settings


def test_variant_settings():
    control = settings_for_variant(AB, "control")
    assert (control.taste_weight, control.dislike_item_weight) == (0.0, 0.0)
    assert control.hide_categories is False
    assert settings_for_variant(AB, "taste") is AB


def test_env_parsing():
    assert RecommenderSettings.from_env({}).ab_variants == ()
    assert RecommenderSettings.from_env({"REC_AB_VARIANTS": " "}).ab_variants == ()
    parsed = RecommenderSettings.from_env({"REC_AB_VARIANTS": "control, taste"})
    assert parsed.ab_variants == ("control", "taste")
    for bad in ("control,other", "taste,taste"):
        with pytest.raises(ValueError, match="REC_AB_VARIANTS"):
            RecommenderSettings.from_env({"REC_AB_VARIANTS": bad})


def _app(settings):
    app = create_app("sqlite:///:memory:", recommender_settings=settings)
    with app.state.session_factory() as session:
        session.add_all([Movie(id=i, title=f"M{i}") for i in range(1, 9)])
        for _ in range(6):
            user = User(is_synthetic=True)
            session.add(user)
            session.flush()
            for movie_id in range(1, 8):
                session.add(Rating(user_id=user.id, movie_id=movie_id, value=1))
        session.commit()
    return app


def _events(app):
    with app.state.session_factory() as session:
        return list(session.scalars(select(Event).order_by(Event.id)))


def test_variant_in_impressions_and_reactions():
    app = _app(AB)
    with TestClient(app) as client:
        client.post("/api/session")
        body = client.get("/api/recommendations?limit=3").json()
        sid = body["session_id"]
        movie_id = body["items"][0]["movie"]["id"]
        assert client.post(
            "/api/ratings", json={"movie_id": movie_id, "value": 1, "session_id": sid}
        ).json()["ok"]
        client.post("/api/seen", json={"movie_id": movie_id, "type": "watched", "session_id": sid})
        client.post("/api/ratings", json={"movie_id": 8, "value": 1, "session_id": "stray"})
    events = _events(app)
    with app.state.session_factory() as session:
        user_id = max(session.scalars(select(User.id)))
    expected = assign_variant(AB, user_id)
    assert expected in ("control", "taste")
    by_session = [e for e in events if e.session_id == sid]
    assert {e.type for e in by_session} == {"impression", "like", "watched"}
    assert all(e.variant == expected for e in by_session)
    assert [e.variant for e in events if e.session_id == "stray"] == [None]


def test_no_variant_when_ab_off():
    app = _app(RecommenderSettings(min_user_ratings=5))
    with TestClient(app) as client:
        client.post("/api/session")
        sid = client.get("/api/recommendations?limit=2").json()["session_id"]
        client.post("/api/ratings", json={"movie_id": 1, "value": 1, "session_id": sid})
    assert {e.variant for e in _events(app)} == {None}
