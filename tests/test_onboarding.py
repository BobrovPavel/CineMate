import pytest
from scipy.sparse import csr_matrix
from sqlalchemy.orm import sessionmaker

from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, SeenMark, User
from cinemate.db.session import create_all, make_engine
from cinemate.services.onboarding import onboarding_for_user, pick_onboarding_movies


def _matrix(columns):
    """columns: list of lists of +1/-1 (one list of votes per movie)."""
    rows, cols, data = [], [], []
    for c, votes in enumerate(columns):
        for r, v in enumerate(votes):
            rows.append(r)
            cols.append(c)
            data.append(v)
    n_users = max(len(v) for v in columns)
    return csr_matrix((data, (rows, cols)), shape=(n_users, len(columns)))


def test_controversial_before_unanimous():
    m = _matrix([[1, 1, 1, 1], [1, -1, 1, -1], [1, 1, 1, -1]])
    assert pick_onboarding_movies(m, [[], [], []]) == [1, 2, 0]


def test_genre_limit_with_fill():
    m = _matrix([[1, -1]] * 5 + [[1, 1]])
    genres = [["Drama"]] * 5 + [["Comedy"]]
    # Drama capped at 3 while Comedy is available
    assert pick_onboarding_movies(m, genres, n=4) == [0, 1, 2, 5]
    # not enough alternatives -> skipped ones fill the rest
    assert pick_onboarding_movies(m, genres, n=6) == [0, 1, 2, 5, 3, 4]
    assert sorted(pick_onboarding_movies(m, genres, n=6)) == [0, 1, 2, 3, 4, 5]


def test_exclude_and_n_larger_than_pool():
    m = _matrix([[1, -1], [1, -1], [1, 1]])
    assert pick_onboarding_movies(m, [[]] * 3, n=50, pool=2, exclude={0}) == [1, 2]


def test_pool_keeps_most_rated():
    m = _matrix([[1, -1, 1], [1, 1, 1], [1, -1, 1]])
    # column 1 has the same count; pool=1 keeps lowest index among ties
    assert pick_onboarding_movies(m, [[]] * 3, pool=1) == [0]


def test_deterministic_ties_and_empty():
    m = _matrix([[1, -1]] * 4)
    assert pick_onboarding_movies(m, [[]] * 4, n=3) == [0, 1, 2]
    assert pick_onboarding_movies(csr_matrix((0, 0)), [], n=3) == []


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return sessionmaker(engine)


def test_onboarding_for_user_excludes_done(factory):
    with factory() as s:
        s.add_all([User(id=1), User(id=2), User(id=3)])
        s.add_all(Movie(id=i, title=f"m{i}", genres=[f"g{i}"]) for i in (1, 2, 3, 4))
        s.flush()
        for mid in (1, 2, 3, 4):
            s.add(Rating(user_id=1, movie_id=mid, value=1))
            s.add(Rating(user_id=2, movie_id=mid, value=-1 if mid != 4 else 1))
        s.add(SeenMark(user_id=3, movie_id=2, type="watched"))
        s.add(Rating(user_id=3, movie_id=1, value=1))
        s.commit()
    store = MatrixStore(factory)
    with factory() as s:
        user = s.get(User, 3)
        movies = onboarding_for_user(s, store, user, n=10)
        assert [m.id for m in movies] == [3, 4]
