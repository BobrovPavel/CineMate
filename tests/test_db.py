import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cinemate.db.models import Movie, Rating, SeenMark, User
from cinemate.db.session import create_all, make_engine


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def user_movie(session):
    user = User(session_token="tok")
    movie = Movie(title="Heat", genres=["Crime"], external_movielens_id=6)
    session.add_all([user, movie])
    session.commit()
    return user, movie


def test_create_all_makes_tables():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    assert set(inspect(engine).get_table_names()) == {
        "movies",
        "users",
        "ratings",
        "seen_marks",
        "events",
    }


def test_insert_and_read(session, user_movie):
    user, movie = user_movie
    session.add(Rating(user_id=user.id, movie_id=movie.id, value=1))
    session.add(SeenMark(user_id=user.id, movie_id=movie.id, type="watched"))
    session.commit()
    session.expire_all()
    assert session.scalars(select(Movie)).one().genres == ["Crime"]
    got = session.scalars(select(User)).one()
    assert got.is_synthetic is False
    assert got.created_at is not None
    assert session.scalars(select(Rating)).one().value == 1
    assert session.scalars(select(SeenMark)).one().type == "watched"


def test_rating_unique(session, user_movie):
    user, movie = user_movie
    session.add(Rating(user_id=user.id, movie_id=movie.id, value=1))
    session.commit()
    session.add(Rating(user_id=user.id, movie_id=movie.id, value=-1))
    with pytest.raises(IntegrityError):
        session.commit()


def test_seen_mark_unique(session, user_movie):
    user, movie = user_movie
    session.add(SeenMark(user_id=user.id, movie_id=movie.id, type="watched"))
    session.commit()
    session.add(SeenMark(user_id=user.id, movie_id=movie.id, type="not_seen"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_rating_value_check(session, user_movie):
    user, movie = user_movie
    session.add(Rating(user_id=user.id, movie_id=movie.id, value=5))
    with pytest.raises(IntegrityError):
        session.commit()


def test_seen_mark_type_check(session, user_movie):
    user, movie = user_movie
    session.add(SeenMark(user_id=user.id, movie_id=movie.id, type="bogus"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_movielens_id_and_session_token_unique(session, user_movie):
    session.add(Movie(title="Dup", external_movielens_id=6))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(User(session_token="tok"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_make_engine_accepts_postgres_url_without_connecting():
    pytest.importorskip("psycopg")
    engine = make_engine("postgresql+psycopg://user:secret@localhost:5432/cinemate")
    assert engine.dialect.name == "postgresql"
    assert engine.url.host == "localhost"
