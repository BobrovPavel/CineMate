import pytest
from scipy.sparse import csr_matrix

from cinemate.recommender.similarity import find_neighbors


def make(rows: list[list[int]]) -> csr_matrix:
    return csr_matrix(rows, dtype="int8")


def test_identical_tastes_give_one():
    m = make([[1, 1, -1, 1, -1], [1, 1, -1, 1, -1]])
    assert find_neighbors(m, 0, min_overlap=5) == [(1, pytest.approx(1.0))]


def test_opposite_tastes_are_excluded():
    m = make([[1, 1, -1, 1, -1], [-1, -1, 1, -1, 1]])
    assert find_neighbors(m, 0, min_overlap=5) == []


def test_overlap_below_threshold_gives_zero():
    m = make([[1, 1, 1, 1, 0], [1, 1, 1, 0, 1]])
    assert find_neighbors(m, 0, min_overlap=4) == []
    assert [i for i, _ in find_neighbors(m, 0, min_overlap=3)] == [1]


def test_k_limits_result():
    m = make([[1, 1, 1]] + [[1, 1, 1]] * 5)
    assert len(find_neighbors(m, 0, k=3, min_overlap=3)) == 3


def test_sorted_descending():
    m = make([[1, 1, 1, 1], [1, 1, 1, 0], [1, 1, 1, 1], [1, 1, 1, -1]])
    result = find_neighbors(m, 0, min_overlap=3)
    assert [i for i, _ in result] == [2, 1, 3]
    sims = [s for _, s in result]
    assert sims == sorted(sims, reverse=True)
    assert sims[0] == pytest.approx(1.0)
    assert sims[1] == pytest.approx(3 / (2 * 3**0.5))
    assert sims[2] == pytest.approx(0.5)


def test_user_is_not_own_neighbor():
    m = make([[1, -1, 1], [1, -1, 1]])
    assert 0 not in [i for i, _ in find_neighbors(m, 0, min_overlap=1)]


def test_empty_row_has_no_neighbors():
    m = make([[0, 0, 0], [1, 1, 1]])
    assert find_neighbors(m, 0, min_overlap=1) == []


def test_non_positive_k():
    m = make([[1, 1], [1, 1]])
    assert find_neighbors(m, 0, k=0, min_overlap=1) == []
