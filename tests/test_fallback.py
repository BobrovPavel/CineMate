import random

from scipy.sparse import csr_matrix

from cinemate.recommender.fallback import popular
from cinemate.recommender.strategy import Recommendation, recommend_with_strategy


def make(rows: list[list[int]]) -> csr_matrix:
    return csr_matrix(rows, dtype="int8")


def crowd(cols: int = 10, users: int = 8) -> list[list[int]]:
    """Users 1.. like movie j with decreasing share: movie 0 most liked."""
    return [[1 if i < users - j else -1 for j in range(cols)] for i in range(users)]


def test_popular_excludes_rated_and_scores_like_share():
    m = make([[1, 0, 0]] + [[1, 1, -1]] * 5)
    result = popular(m, 0, n=5, rng=random.Random(0))
    assert result == [(1, 1.0), (2, 0.0)]


def test_popular_requires_min_ratings():
    m = make([[0, 0], [1, 1], [1, 0], [1, 0], [1, 0], [1, 0]])
    result = popular(m, 0, n=5, min_ratings=5)
    assert [i for i, _ in result] == [0]


def test_popular_deterministic_with_seed_and_limited_to_pool():
    m = make([[0] * 10] + crowd())
    a = popular(m, 0, n=2, rng=random.Random(42))
    b = popular(m, 0, n=2, rng=random.Random(42))
    assert a == b
    assert len(a) == 2
    assert all(i < 6 for i, _ in a)  # top 3 * n = 6 pool
    assert a == sorted(a, key=lambda p: (-p[1], p[0]))


def test_popular_edge_cases():
    m = make([[0, 0], [1, 1]])
    assert popular(m, 0, n=0) == []
    assert popular(m, 0, n=3, min_ratings=5) == []


def test_empty_profile_uses_fallback():
    m = make([[0] * 10] + crowd())
    result = recommend_with_strategy(m, 0, rng=random.Random(1))
    assert isinstance(result, Recommendation)
    assert result.strategy == "fallback"
    assert result.items


def test_few_ratings_use_fallback_even_with_neighbors():
    m = make([[1, 1, 1, 1, 0, 0, 0]] + [[1, 1, 1, 1, 1, 1, 0]] * 3)
    assert recommend_with_strategy(m, 0, min_overlap=1).strategy == "fallback"


def test_enough_ratings_and_neighbors_use_collaborative():
    rows = [[1, 1, 1, 1, 1, 0, 0]] + [[1, 1, 1, 1, 1, 1, 0]] * 3
    m = make(rows)
    result = recommend_with_strategy(m, 0, min_overlap=5)
    assert result.strategy == "collaborative"
    assert [i for i, _ in result.items] == [5]


def test_no_neighbors_falls_back():
    rows = [[1, 1, 1, 1, 1, 0, 0]] + [[-1, -1, -1, -1, -1, 1, 1]] * 6
    result = recommend_with_strategy(make(rows), 0, rng=random.Random(0))
    assert result.strategy == "fallback"
    assert not {0, 1, 2, 3, 4} & {i for i, _ in result.items}
