import random

import pytest
from sqlalchemy.orm import sessionmaker

from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, SeenMark, User
from cinemate.db.session import create_all, make_engine
from cinemate.services.recommendations import get_recommendations

N_MOVIES = 12
N_USERS = 8


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
    result = get_recommendations(session, store, session.get(User, 1))
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
