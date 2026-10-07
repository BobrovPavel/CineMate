import math

import pytest
from scipy.sparse import csr_matrix

from cinemate.recommender.scoring import recommend


def make(rows: list[list[int]]) -> csr_matrix:
    return csr_matrix(rows, dtype="int8")


def likes_matrix(*liked: list[int], cols: int = 10) -> csr_matrix:
    """Rows of +1 at the given 1-based movie numbers."""
    return make([[1 if j + 1 in movies else 0 for j in range(cols)] for movies in liked])


def test_scenario_x_gets_8_and_9():
    m = likes_matrix([1, 2, 3, 4, 5, 6, 7], [1, 2, 3, 5, 7, 8, 9])
    result = recommend(m, 0, min_overlap=5)
    assert sorted(i for i, _ in result) == [7, 8]  # movies 8 and 9 (0-based 7, 8)
    assert all(score > 0 for _, score in result)


def test_neighbor_dislikes_lower_score():
    m = make(
        [
            [1, 1, 1, 0, 0],
            [1, 1, 1, 1, -1],
            [1, 1, 1, 1, 0],
        ]
    )
    scores = dict(recommend(m, 0, min_overlap=3))
    assert scores[4] < 0 < scores[3]


def test_rated_movies_are_excluded():
    m = make([[1, -1, 1, 0], [1, -1, 1, 1], [1, -1, 1, 1]])
    assert [i for i, _ in recommend(m, 0, min_overlap=3)] == [3]


def test_shrinkage_lowers_score_for_small_support():
    m = make([[1, 1, 1, 0], [1, 1, 1, 1], [1, 1, 1, 1]])
    (_, strong) = recommend(m, 0, min_overlap=3, lam=5.0)[0]
    (_, weak) = recommend(m, 0, min_overlap=3, lam=50.0)[0]
    assert weak < strong
    # two supporting neighbours, sims = 1, norm = 1, likes = 2
    assert strong == pytest.approx(2 / (2 + 5) / math.log(4))


def test_popularity_penalty():
    # Movies 3 and 4 are liked by both neighbours; movie 4 also by extra users.
    m = make(
        [
            [1, 1, 1, 0, 0],
            [1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1],
            [0, 0, 0, 0, 1],
            [0, 0, 0, 0, 1],
        ]
    )
    scores = dict(recommend(m, 0, min_overlap=3))
    assert scores[3] > scores[4]


def test_no_neighbors_gives_empty_list():
    m = make([[1, 1, 1], [-1, -1, -1]])
    assert recommend(m, 0, min_overlap=1) == []


def test_n_limits_and_sorts():
    m = make([[1, 1, 0, 0, 0], [1, 1, 1, 1, 1], [1, 1, 1, 1, 0]])
    full = recommend(m, 0, min_overlap=2)
    assert [s for _, s in full] == sorted((s for _, s in full), reverse=True)
    assert recommend(m, 0, n=1, min_overlap=2) == full[:1]
    assert recommend(m, 0, n=0, min_overlap=2) == []
