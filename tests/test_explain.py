from scipy.sparse import csr_matrix

from cinemate.recommender.explain import Explanation, Twin, explain


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


def likes_rows(n_cols: int, *liked: list[int]) -> csr_matrix:
    return make([[1 if j in movies else 0 for j in range(n_cols)] for movies in liked])


def test_twin_when_one_close_neighbour_gives_the_movie():
    # user likes 0..9; twin shares 0..7 and likes 10; a weak neighbour likes 0 and 10 too
    m = likes_rows(11, list(range(10)), [*range(8), 10], [0, 10])
    result = explain(m, 0, 10, [(1, 0.8), (2, 0.1)], sim_power=2.5)
    assert result.liked_by == 2
    assert result.twin == Twin(common=8, of=10)


def test_no_twin_with_fewer_than_five_common_likes():
    m = likes_rows(8, [0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 7])
    assert explain(m, 0, 7, [(1, 0.9)]).twin is None


def test_no_twin_with_less_than_sixty_percent_of_likes():
    m = likes_rows(12, list(range(10)), [*range(5), 11])  # 5 of 10 likes
    assert explain(m, 0, 11, [(1, 0.9)]).twin is None


def test_no_twin_when_many_neighbours_share_the_credit():
    m = likes_rows(11, list(range(10)), [*range(8), 10], *([[0, 10]] * 6))
    neighbors = [(1, 0.8)] + [(i, 0.7) for i in range(2, 8)]
    assert explain(m, 0, 10, neighbors, sim_power=1.0).twin is None
