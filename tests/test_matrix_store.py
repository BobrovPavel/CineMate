import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, User
from cinemate.db.session import create_all, make_engine


@pytest.fixture
def engine():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return engine


@pytest.fixture
def factory(engine):
    return sessionmaker(engine)


def _seed(factory, ratings):
    """ratings: list of (user_id, movie_id, value); creates users/movies as needed."""
    with factory() as s:
        for uid in {u for u, _, _ in ratings}:
            if s.get(User, uid) is None:
                s.add(User(id=uid))
        for mid in {m for _, m, _ in ratings}:
            if s.get(Movie, mid) is None:
                s.add(Movie(id=mid, title=f"m{mid}"))
        s.flush()
        s.add_all(Rating(user_id=u, movie_id=m, value=v) for u, m, v in ratings)
        s.commit()


def test_empty_db_gives_empty_matrix(factory):
    result = MatrixStore(factory).get()
    assert result.matrix.shape == (0, 0)
    assert result.user_ids == []
    assert result.movie_ids == []


def test_matrix_matches_db(factory):
    _seed(factory, [(1, 10, 1), (1, 20, -1), (2, 20, 1)])
    result = MatrixStore(factory).get()
    assert result.user_ids == [1, 2]
    assert result.movie_ids == [10, 20]
    assert result.matrix.toarray().tolist() == [[1, -1], [0, 1]]


def test_second_get_does_not_query(engine, factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory)
    first = store.get()

    statements = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    second = store.get()

    assert second is first
    assert statements == []


def test_invalidate_reveals_new_ratings(factory):
    _seed(factory, [(1, 10, 1)])
    store = MatrixStore(factory)
    assert store.get().matrix.shape == (1, 1)

    _seed(factory, [(2, 20, -1)])
    assert store.get().matrix.shape == (1, 1)  # still cached

    store.invalidate()
    assert store.get().matrix.shape == (1, 1)  # stale matrix is served until a rebuild
    store.rebuild_now()
    result = store.get()
    assert result.user_ids == [1, 2]
    assert result.movie_ids == [10, 20]


def test_session_is_closed_after_load(factory):
    closed = []
    original = Session.close
    Session.close = lambda self: (closed.append(1), original(self))[1]
    try:
        MatrixStore(factory).get()
    finally:
        Session.close = original
    assert closed


def test_store_caches_content_features_of_the_columns(factory):
    from cinemate.db.models import MovieGenre

    _seed(factory, [(1, 1, 1), (1, 2, 1), (2, 1, 1)])
    with factory() as s:
        s.get(Movie, 1).tmdb_type = "movie"
        s.get(Movie, 1).year = 1994
        s.add_all([MovieGenre(movie_id=1, genre_id=14), MovieGenre(movie_id=1, genre_id=18)])
        s.commit()
    taste = MatrixStore(factory).get().taste
    assert taste is not None
    assert [("genre", 14) in g[0] for g in taste.groups[:1]] == [True]
    assert taste.groups[1] == ()  # movie 2 has no features
    assert taste.base[("genre", 14)] == pytest.approx(2 / 3)  # movie 1 holds 2 of 3 likes
    assert taste.primary_genre == [14, None]
