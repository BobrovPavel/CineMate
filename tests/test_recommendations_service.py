import random

import pytest
from sqlalchemy.orm import sessionmaker

from cinemate.config import RecommenderSettings
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, SeenMark, User
from cinemate.db.session import create_all, make_engine
from cinemate.recommender.explain import Twin
from cinemate.services import recommendations as recommendations_module
from cinemate.services.recommendations import get_recommendations

N_MOVIES = 12
N_USERS = 8
FIVE = RecommenderSettings(min_user_ratings=5)  # the fixture users have only 6 ratings


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return sessionmaker(engine)


@pytest.fixture
def session(factory):
    """Users 1..8 like movies 1..6; users 2..8 also like movie 7+ (user 1 is the target)."""
    with factory() as s:
        s.add_all([Movie(id=i, title=f"m{i}") for i in range(1, N_MOVIES + 1)])
        s.add_all([User(id=i) for i in range(1, N_USERS + 1)])
        s.add_all([User(id=100)])  # no ratings
        s.flush()
        for u in range(1, N_USERS + 1):
            for m in range(1, 7):
                s.add(Rating(user_id=u, movie_id=m, value=1))
        for u in range(2, N_USERS + 1):
            for m in (7, 8, 9):
                s.add(Rating(user_id=u, movie_id=m, value=1))
        s.flush()
        s.commit()
        yield s


@pytest.fixture
def store(factory):
    return MatrixStore(factory)


def test_user_without_ratings_gets_fallback(session, store):
    result = get_recommendations(session, store, session.get(User, 100), rng=random.Random(0))
    assert result.strategy == "fallback"
    assert result.items
    assert all(i.liked_by == 0 and i.because_of == [] for i in result.items)


def test_unknown_in_empty_store_is_fallback(factory):
    with factory() as s:
        s.add(User(id=1))
        s.flush()
        result = get_recommendations(s, MatrixStore(factory), s.get(User, 1))
    assert result.strategy == "fallback"
    assert result.items == []


def test_collaborative_with_explanations(session, store):
    result = get_recommendations(session, store, session.get(User, 1), settings=FIVE)
    assert result.strategy == "collaborative"
    assert {i.movie.id for i in result.items} == {7, 8, 9}
    for item in result.items:
        assert item.liked_by > 0
        assert 0 < len(item.because_of) <= 3
        assert all(b.id <= 6 for b in item.because_of)


def test_watched_and_not_interested_excluded_not_seen_kept(session, store):
    session.add_all(
        [
            SeenMark(user_id=1, movie_id=7, type="watched"),
            SeenMark(user_id=1, movie_id=8, type="not_interested"),
            SeenMark(user_id=1, movie_id=9, type="not_seen"),
        ]
    )
    session.commit()  # MatrixStore shares the in-memory connection and would roll back
    result = get_recommendations(session, store, session.get(User, 1))
    assert [i.movie.id for i in result.items] == [9]


def test_limit_applies_after_exclusion(session, store):
    session.add(SeenMark(user_id=1, movie_id=7, type="watched"))
    session.commit()
    result = get_recommendations(session, store, session.get(User, 1), limit=2)
    assert len(result.items) == 2
    assert 7 not in {i.movie.id for i in result.items}


def test_fallback_excludes_marked_and_is_deterministic(session, store):
    session.add(SeenMark(user_id=100, movie_id=1, type="watched"))
    session.commit()
    user = session.get(User, 100)
    a = get_recommendations(session, store, user, rng=random.Random(1))
    b = get_recommendations(session, store, user, rng=random.Random(1))
    assert [i.movie.id for i in a.items] == [i.movie.id for i in b.items]
    assert 1 not in {i.movie.id for i in a.items}


def test_non_positive_limit(session, store):
    assert get_recommendations(session, store, session.get(User, 1), limit=0).items == []


def test_lambda_from_settings_changes_scores(session, store):
    user = session.get(User, 1)
    low = get_recommendations(
        session,
        store,
        user,
        settings=RecommenderSettings(lam=0.0, min_user_ratings=5, shrink="count"),
    )
    high = get_recommendations(
        session,
        store,
        user,
        settings=RecommenderSettings(lam=1000.0, min_user_ratings=5, shrink="count"),
    )
    assert {i.movie.id: i.score for i in low.items} != {i.movie.id: i.score for i in high.items}
    assert max(i.score for i in low.items) > max(i.score for i in high.items)


def test_settings_are_passed_to_strategy(session, store, monkeypatch):
    seen = {}
    real = recommendations_module.recommend_with_strategy

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(recommendations_module, "recommend_with_strategy", spy)
    get_recommendations(
        session, store, session.get(User, 1), settings=RecommenderSettings(3, 7.0, 2, 0.5, 4, 1)
    )
    assert (seen["k"], seen["lam"], seen["min_overlap"], seen["pop_penalty"]) == (3, 7.0, 2, 0.5)
    assert (seen["min_user_ratings"], seen["fallback_pool_factor"]) == (4, 1)
    assert seen["significance"] == 0


def test_mass_settings_reach_strategy(session, store, monkeypatch):
    seen = {}
    real = recommendations_module.recommend_with_strategy

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(recommendations_module, "recommend_with_strategy", spy)
    get_recommendations(
        session,
        store,
        session.get(User, 1),
        settings=RecommenderSettings(
            min_user_ratings=5, sim_power=3.0, shrink="count", mass_lambda=0.25
        ),
    )
    assert (seen["sim_power"], seen["shrink"], seen["mass_lambda"]) == (3.0, "count", 0.25)


def test_significance_reaches_strategy_and_explanations(session, store, monkeypatch):
    seen = {}
    real_strategy = recommendations_module.recommend_with_strategy
    real_neighbors = recommendations_module.find_neighbors

    def spy_strategy(*args, **kwargs):
        seen["strategy"] = kwargs["significance"]
        return real_strategy(*args, **kwargs)

    def spy_neighbors(*args, **kwargs):
        seen["neighbors"] = kwargs["significance"]
        return real_neighbors(*args, **kwargs)

    monkeypatch.setattr(recommendations_module, "recommend_with_strategy", spy_strategy)
    monkeypatch.setattr(recommendations_module, "find_neighbors", spy_neighbors)
    result = get_recommendations(
        session,
        store,
        session.get(User, 1),
        settings=RecommenderSettings(min_user_ratings=5, significance=3),
    )
    assert result.strategy == "collaborative"
    assert seen == {"strategy": 3, "neighbors": 3}


def test_default_settings_used_without_argument(session, store, monkeypatch):
    seen = {}
    real = recommendations_module.recommend_with_strategy

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(recommendations_module, "recommend_with_strategy", spy)
    get_recommendations(session, store, session.get(User, 1))
    assert seen["lam"] == RecommenderSettings().lam


def test_four_ratings_get_fallback_and_five_get_collaborative(session, store):
    user = session.get(User, 100)
    session.add_all([Rating(user_id=100, movie_id=m, value=1) for m in (1, 2, 3, 4)])
    session.commit()
    store.invalidate()
    assert get_recommendations(session, store, user, rng=random.Random(0)).strategy == "fallback"
    session.add(Rating(user_id=100, movie_id=5, value=1))
    session.commit()
    store.invalidate()
    assert get_recommendations(session, store, user).strategy == "collaborative"


def test_blend_full_at_setting_enables_hybrid(session, store):
    user = session.get(User, 1)
    # User 1 has 6 ratings: beta = 6/10 >= 0.5 -> collaborative even though min_user_ratings=50.
    settings = RecommenderSettings(min_user_ratings=50, blend_full_at=10.0)
    result = get_recommendations(session, store, user, settings=settings, rng=random.Random(0))
    assert result.strategy == "collaborative"
    assert {i.movie.id for i in result.items} >= {7, 8, 9}
    off = get_recommendations(
        session,
        store,
        user,
        settings=RecommenderSettings(min_user_ratings=50),
        rng=random.Random(0),
    )
    assert off.strategy == "fallback"


def test_twin_scenario_with_default_settings(factory):
    """X likes 1..10; twin Z likes 1..8, 11, 12; 300 others like random popular movies."""
    rng = random.Random(0)
    popular = list(range(13, 63))
    with factory() as s:
        s.add_all([Movie(id=i, title=f"m{i}") for i in range(1, 63)])
        s.add_all([User(id=i) for i in range(1, 303)])
        s.flush()
        for m in range(1, 11):
            s.add(Rating(user_id=1, movie_id=m, value=1))
        for m in [*range(1, 9), 11, 12]:
            s.add(Rating(user_id=2, movie_id=m, value=1))
        for u in range(3, 303):
            for m in rng.sample(popular, 8):
                s.add(Rating(user_id=u, movie_id=m, value=1))
        s.commit()
    with factory() as s:
        result = get_recommendations(s, MatrixStore(factory), s.get(User, 1), limit=10)
    assert result.strategy == "collaborative"
    assert {i.movie.id for i in result.items[:3]} >= {11, 12}


def test_default_settings_keep_x_gets_8_and_9(factory):
    with factory() as s:
        s.add_all([Movie(id=i, title=f"m{i}") for i in range(1, 11)])
        s.add_all([User(id=1), User(id=2)])
        s.flush()
        for m in range(1, 8):
            s.add(Rating(user_id=1, movie_id=m, value=1))
        for m in (1, 2, 3, 5, 7, 8, 9):
            s.add(Rating(user_id=2, movie_id=m, value=1))
        s.commit()
    with factory() as s:
        result = get_recommendations(s, MatrixStore(factory), s.get(User, 1), limit=10)
    assert {i.movie.id for i in result.items[:2]} == {8, 9}


def test_twin_explanation_in_the_service(session, store):
    # users 2..8 all share the target's six likes and like 7, 8, 9: no single neighbour leads
    result = get_recommendations(session, store, session.get(User, 1), settings=FIVE)
    assert result.items and all(i.twin is None for i in result.items)


def test_twin_explanation_for_a_close_neighbour(factory):
    with factory() as s:
        s.add_all([Movie(id=i, title=f"m{i}") for i in range(1, 14)])
        s.add_all([User(id=1), User(id=2), User(id=3)])
        s.flush()
        for m in range(1, 11):
            s.add(Rating(user_id=1, movie_id=m, value=1))
        for m in [*range(1, 9), 11, 12]:
            s.add(Rating(user_id=2, movie_id=m, value=1))
        for m in (1, 13):
            s.add(Rating(user_id=3, movie_id=m, value=1))
        s.commit()
    with factory() as s:
        result = get_recommendations(s, MatrixStore(factory), s.get(User, 1))
    twins = {i.movie.id: i.twin for i in result.items}
    assert twins[11] == Twin(common=8, of=10)
    assert twins[12] == Twin(common=8, of=10)
