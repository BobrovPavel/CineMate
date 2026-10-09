import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from cinemate.db.models import Event, Movie
from cinemate.db.session import create_all, make_engine
from cinemate.services.events import log_impressions, log_reaction
from cinemate.services.users import create_session_user


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with sessionmaker(engine)() as s:
        s.add_all([Movie(id=1, title="a"), Movie(id=2, title="b")])
        s.flush()
        yield s


def test_log_impressions_one_row_per_movie(session):
    user = create_session_user(session)
    events = log_impressions(session, user, "s1", [1, 2], "collaborative")
    assert len(events) == 2
    rows = session.scalars(select(Event).order_by(Event.id)).all()
    assert [(e.type, e.movie_id, e.strategy, e.session_id) for e in rows] == [
        ("impression", 1, "collaborative", "s1"),
        ("impression", 2, "collaborative", "s1"),
    ]
    assert all(e.user_id == user.id and e.created_at is not None for e in rows)


def test_log_impressions_empty_list(session):
    user = create_session_user(session)
    assert log_impressions(session, user, "s1", [], "fallback") == []
    assert session.scalars(select(Event)).all() == []


def test_log_impressions_invalid_strategy(session):
    user = create_session_user(session)
    with pytest.raises(ValueError):
        log_impressions(session, user, "s1", [1], "magic")


def test_log_reaction(session):
    user = create_session_user(session)
    for t in ("like", "dislike", "watched", "not_interested"):
        event = log_reaction(session, user, "s1", 1, t)
        assert event.type == t and event.strategy is None and event.movie_id == 1


@pytest.mark.parametrize("bad", ["impression", "love", ""])
def test_log_reaction_invalid_type(session, bad):
    user = create_session_user(session)
    with pytest.raises(ValueError):
        log_reaction(session, user, "s1", 1, bad)


def test_db_check_constraints(session):
    user = create_session_user(session)
    session.add(Event(user_id=user.id, session_id="s", type="bogus"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_db_strategy_constraint(session):
    user = create_session_user(session)
    session.add(Event(user_id=user.id, session_id="s", type="impression", strategy="x"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
