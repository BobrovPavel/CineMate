from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cinemate.db.catalog import CatalogConflict, find_movie, link, merge_movies
from cinemate.db.models import Event, Movie, MovieExternalId, Rating, SeenMark, User
from cinemate.db.session import create_all, make_engine


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with Session(engine) as s:
        yield s


def _movie(session, title="Heat", **kw):
    movie = Movie(title=title, **kw)
    session.add(movie)
    session.flush()
    return movie


def test_find_by_tmdb_pair_distinguishes_type(session):
    film = _movie(session, "Film", tmdb_type="movie", tmdb_id=1399)
    show = _movie(session, "Show", tmdb_type="tv", tmdb_id=1399)
    assert find_movie(session, tmdb=("movie", 1399)) is film
    assert find_movie(session, tmdb=("tv", 1399)) is show
    assert find_movie(session, tmdb=("movie", 5)) is None
    assert find_movie(session) is None


def test_tmdb_pair_is_unique(session):
    _movie(session, tmdb_type="movie", tmdb_id=1)
    session.add(Movie(title="Dup", tmdb_type="movie", tmdb_id=1))
    with pytest.raises(IntegrityError):
        session.flush()


def test_find_by_external_ids_uses_source_order_and_tmdb_first(session):
    a, b, c = _movie(session, "A"), _movie(session, "B"), _movie(session, "C")
    link(session, a, "movielens", 1)
    link(session, b, "imdb", "tt1")
    link(session, c, "tmdb-holder", "x")
    c.tmdb_type, c.tmdb_id = "movie", 7
    session.flush()
    assert find_movie(session, ids={"movielens": "1", "imdb": "tt1"}) is b
    assert find_movie(session, ids={"movielens": "1", "kinopoisk": "9"}) is a
    assert find_movie(session, ids={"movielens": 1}) is a
    assert find_movie(session, tmdb=("movie", 7), ids={"imdb": "tt1"}) is c
    assert find_movie(session, tmdb=("movie", 8), ids={"imdb": "tt1"}) is b
    assert find_movie(session, ids={"ratings_csv": "1"}) is None


def test_link_conflict_and_repeat(session):
    a, b = _movie(session, "A"), _movie(session, "B")
    link(session, a, "movielens", 1)
    link(session, a, "movielens", 1)
    session.flush()
    assert session.scalar(select(MovieExternalId).where(MovieExternalId.movie_id == a.id))
    with pytest.raises(CatalogConflict):
        link(session, b, "movielens", "1")
    assert session.get(MovieExternalId, ("movielens", "1")).movie_id == a.id
    link(session, a, "movielens", 2)  # several ids of one source per movie


def _rating(session, user, movie, value, day):
    session.add(
        Rating(
            user_id=user.id,
            movie_id=movie.id,
            value=value,
            created_at=datetime(2024, 1, day, tzinfo=UTC),
        )
    )


def test_merge_movies_moves_everything_and_keeps_newer_rating(session):
    keep, drop = _movie(session, "Keep"), _movie(session, "Drop")
    u1, u2, u3 = (User(), User(), User())
    session.add_all([u1, u2, u3])
    session.flush()
    link(session, drop, "movielens", 5)
    link(session, keep, "imdb", "tt1")
    _rating(session, u1, keep, 1, 1)
    _rating(session, u1, drop, -1, 2)  # newer: wins
    _rating(session, u2, keep, -1, 3)  # newer: stays
    _rating(session, u2, drop, 1, 1)
    _rating(session, u3, drop, 1, 1)  # moved
    session.add_all(
        [
            SeenMark(user_id=u1.id, movie_id=keep.id, type="watched"),
            SeenMark(user_id=u1.id, movie_id=drop.id, type="not_interested"),
            SeenMark(user_id=u2.id, movie_id=drop.id, type="watched"),
        ]
    )
    session.add(Event(user_id=u1.id, session_id="s", type="like", movie_id=drop.id))
    session.flush()
    keep_id, drop_id = keep.id, drop.id

    merge_movies(session, keep_id, drop_id)

    assert session.get(Movie, drop_id) is None
    ratings = {(r.user_id, r.movie_id): r.value for r in session.scalars(select(Rating)).all()}
    assert ratings == {(u1.id, keep_id): -1, (u2.id, keep_id): -1, (u3.id, keep_id): 1}
    marks = {(m.user_id, m.movie_id): m.type for m in session.scalars(select(SeenMark))}
    assert marks == {(u1.id, keep_id): "not_interested", (u2.id, keep_id): "watched"}
    assert session.scalars(select(Event.movie_id)).all() == [keep_id]
    assert find_movie(session, ids={"movielens": "5"}).id == keep_id
    assert find_movie(session, ids={"imdb": "tt1"}).id == keep_id


def test_merge_movie_into_itself_is_a_noop(session):
    movie = _movie(session)
    merge_movies(session, movie.id, movie.id)
    assert session.get(Movie, movie.id) is not None


def test_merge_keeps_tmdb_pair_of_dropped_movie_when_keep_has_none(session):
    keep, drop = _movie(session, "Keep"), _movie(session, "Drop", tmdb_type="tv", tmdb_id=5)
    merge_movies(session, keep.id, drop.id)
    assert find_movie(session, tmdb=("tv", 5)).id == keep.id
