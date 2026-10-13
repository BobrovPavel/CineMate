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


def test_dislikes_count_towards_overlap():
    m = make([[-1, -1, 1], [-1, -1, 1]])
    assert [i for i, _ in find_neighbors(m, 0, min_overlap=3)] == [1]


def equal_cosine_matrix() -> csr_matrix:
    # Neighbours 1 (overlap 1) and 2 (overlap 5) both have cosine 1 / sqrt(5) with user 0.
    rows = [[0] * 25 for _ in range(3)]
    for j in range(5):
        rows[0][j] = 1
    rows[1][0] = 1
    for j in range(25):
        rows[2][j] = 1
    return make(rows)


def test_significance_weights_by_overlap_and_reorders():
    m = equal_cosine_matrix()
    plain = find_neighbors(m, 0, min_overlap=1)
    assert [i for i, _ in plain] == [1, 2]  # tie, broken by index
    assert plain[0][1] == pytest.approx(plain[1][1])
    weighted = dict(find_neighbors(m, 0, min_overlap=1, significance=5))
    assert weighted[1] == pytest.approx(0.2 * plain[0][1])
    assert weighted[2] == pytest.approx(1.0 * plain[1][1])
    assert [i for i, _ in find_neighbors(m, 0, min_overlap=1, significance=5)] == [2, 1]


def test_significance_zero_matches_default():
    m = equal_cosine_matrix()
    assert find_neighbors(m, 0, min_overlap=1, significance=0) == find_neighbors(
        m, 0, min_overlap=1
    )


def test_significance_caps_weight_at_one():
    m = equal_cosine_matrix()
    assert find_neighbors(m, 0, min_overlap=1, significance=3)[0][0] == 2
    assert dict(find_neighbors(m, 0, min_overlap=1, significance=3))[2] == pytest.approx(5**0.5 / 5)


def test_top_k_is_taken_after_weighting():
    m = equal_cosine_matrix()
    assert [i for i, _ in find_neighbors(m, 0, k=1, min_overlap=1)] == [1]
    assert [i for i, _ in find_neighbors(m, 0, k=1, min_overlap=1, significance=5)] == [2]


def test_significance_negative_raises():
    with pytest.raises(ValueError, match="significance"):
        find_neighbors(equal_cosine_matrix(), 0, significance=-1)
