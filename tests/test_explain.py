from scipy.sparse import csr_matrix

from cinemate.recommender.explain import Explanation, explain


def make(rows: list[list[int]]) -> csr_matrix:
    return csr_matrix(rows, dtype="int8")


def nb(*rows: int) -> list[tuple[int, float]]:
    return [(r, 1.0) for r in rows]


def test_liked_by_counts_neighbor_likes():
    m = make([[1, 1, 0, 0], [1, 1, 1, 0], [1, 0, 1, 0], [1, 1, 0, 1]])
    assert explain(m, 0, 2, nb(1, 2, 3)).liked_by == 2


def test_dislikes_are_not_likes():
    m = make([[1, 1, 0], [1, 1, -1], [1, 0, -1]])
    result = explain(m, 0, 2, nb(1, 2))
    assert result == Explanation(liked_by=0, because_of=[])


def test_because_of_order_by_frequency_then_index():
    m = make(
        [
            [1, 1, 1, 0, 0],
            [1, 1, 0, 1, 0],
            [0, 1, 1, 1, 0],
            [0, 1, 0, 1, 0],
        ]
    )
    # movie 3 liked by rows 1, 2, 3; movie 1 in all three, movie 0 in one, movie 2 in one
    result = explain(m, 0, 3, nb(1, 2, 3))
    assert result.liked_by == 3
    assert result.because_of == [1, 0, 2]


def test_because_of_at_most_three():
    m = make([[1, 1, 1, 1, 1, 0], [1, 1, 1, 1, 1, 1]])
    assert explain(m, 0, 5, nb(1)).because_of == [0, 1, 2]


def test_no_common_movies_gives_empty_because_of():
    m = make([[1, 0, 0], [0, 1, 1]])
    result = explain(m, 0, 2, nb(1))
    assert result == Explanation(liked_by=1, because_of=[])


def test_user_dislikes_are_not_because_of():
    m = make([[-1, 1, 0], [1, 1, 1]])
    assert explain(m, 0, 2, nb(1)).because_of == [1]


def test_only_given_neighbors_counted():
    m = make([[1, 0, 0], [1, 0, 1], [1, 0, 1]])
    assert explain(m, 0, 2, nb(1)).liked_by == 1


def test_empty_neighbors():
    m = make([[1, 0], [1, 1]])
    assert explain(m, 0, 1, []) == Explanation(liked_by=0, because_of=[])
