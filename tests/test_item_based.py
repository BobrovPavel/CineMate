import numpy as np
import pytest
from scipy.sparse import csr_matrix

from cinemate.recommender.item_based import recommend_item_based

# users x movies; user 0 liked movie 0 and disliked movie 1.
M = csr_matrix(
    np.array(
        [
            [1, -1, 0, 0],
            [1, 0, 1, 0],
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 1, 0, 1],
        ]
    )
)


def test_manual_example():
    # Movie 2 is rated by users 1, 2 together with movie 0: sim(2, 0) = 2 / sqrt(2 * 3) > 0;
    # user 0 liked movie 0, norm = 1, c = 1 -> score = 1 * 1 / (1 + 5).
    # Movie 3 is rated by users 3, 4 together with movie 1: sim(3, 1) = 2 / sqrt(2 * 3) > 0;
    # user 0 disliked movie 1, norm = -1 -> score = -1 / 6.
    result = dict(recommend_item_based(M, 0, min_overlap=2, lam=5.0))
    assert result == pytest.approx({2: 1 / 6, 3: -1 / 6})
    assert [m for m, _ in recommend_item_based(M, 0, min_overlap=2)] == [2, 3]


def test_rated_movies_excluded():
    assert {m for m, _ in recommend_item_based(M, 0, min_overlap=1)}.isdisjoint({0, 1})


def test_dislike_on_close_movie_lowers_score():
    liked = csr_matrix(np.array([[1, 0], [1, 1], [1, 1]]))
    disliked = csr_matrix(np.array([[-1, 0], [1, 1], [1, 1]]))
    up = dict(recommend_item_based(liked, 0, min_overlap=1))[1]
    down = dict(recommend_item_based(disliked, 0, min_overlap=1))[1]
    assert up > 0 > down


def test_min_overlap_zeroes_similarity():
    assert recommend_item_based(M, 0, min_overlap=3) == []
    assert recommend_item_based(M, 0, min_overlap=2) != []


def test_no_ratings_or_bad_n():
    m = csr_matrix(np.array([[0, 0, 0], [1, 1, 0]]))
    assert recommend_item_based(m, 0, min_overlap=1) == []
    assert recommend_item_based(M, 0, n=0) == []
    assert recommend_item_based(M, 0, n=-1) == []


def test_deterministic_and_ties_by_index():
    m = csr_matrix(np.array([[1, 0, 0, 0], [1, 1, 1, 0], [1, 1, 1, 0]]))
    first = recommend_item_based(m, 0, min_overlap=1)
    assert first == recommend_item_based(m, 0, min_overlap=1)
    assert [i for i, _ in first] == [1, 2]
    assert first[0][1] == pytest.approx(first[1][1])


def test_n_limits_result():
    assert len(recommend_item_based(M, 0, n=1, min_overlap=2)) == 1
