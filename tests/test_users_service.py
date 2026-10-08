import pytest
from sqlalchemy.orm import sessionmaker

from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, SeenMark
from cinemate.db.session import create_all, make_engine
from cinemate.services.users import (
    create_session_user,
    get_ratings,
    get_user_by_token,
    set_rating,
    set_seen_mark,
)


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return sessionmaker(engine)


@pytest.fixture
def session(factory):
    with factory() as s:
        s.add_all([Movie(id=1, title="a"), Movie(id=2, title="b")])
        s.flush()
        yield s


def test_create_and_find_by_token(session):
    u1 = create_session_user(session)
    u2 = create_session_user(session)
    assert u1.session_token and u1.session_token != u2.session_token
    assert u1.is_synthetic is False
    assert get_user_by_token(session, u1.session_token) is u1
    assert get_user_by_token(session, "nope") is None


def test_rating_upsert(session):
    user = create_session_user(session)
    set_rating(session, user, 1, 1)
    set_rating(session, user, 1, -1)
    ratings = get_ratings(session, user)
    assert [(r.movie_id, r.value) for r in ratings] == [(1, -1)]
    assert session.query(Rating).count() == 1


def test_rating_invalid_value_and_unknown_movie(session):
    user = create_session_user(session)
    with pytest.raises(ValueError):
        set_rating(session, user, 1, 0)
    with pytest.raises(ValueError):
        set_rating(session, user, 1, True)
    with pytest.raises(LookupError):
        set_rating(session, user, 99, 1)
    assert get_ratings(session, user) == []


def test_rating_invalidates_store(session, factory):
    user = create_session_user(session)
    session.commit()
    store = MatrixStore(factory)
    assert store.get().matrix.shape == (0, 0)
    set_rating(session, user, 1, 1, store=store)
    session.commit()
    assert store.get().matrix.shape == (1, 1)


def test_seen_mark_change_and_validation(session):
    user = create_session_user(session)
    set_seen_mark(session, user, 1, "watched")
    set_seen_mark(session, user, 1, "not_interested")
    marks = session.query(SeenMark).all()
    assert [(m.movie_id, m.type) for m in marks] == [(1, "not_interested")]
    assert get_ratings(session, user) == []
    with pytest.raises(ValueError):
        set_seen_mark(session, user, 1, "bogus")
    with pytest.raises(LookupError):
        set_seen_mark(session, user, 99, "watched")
