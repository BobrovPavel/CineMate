import random

from scipy.sparse import csr_matrix

from cinemate.recommender.fallback import popular
from cinemate.recommender.strategy import Recommendation, recommend_with_strategy


def make(rows: list[list[int]]) -> csr_matrix:
    return csr_matrix(rows, dtype="int8")


def crowd(cols: int = 10, users: int = 8) -> list[list[int]]:
    """Users 1.. like movie j with decreasing share: movie 0 most liked."""
    return [[1 if i < users - j else -1 for j in range(cols)] for i in range(users)]


def test_popular_excludes_rated_and_scores_relative_to_max_likes():
    m = make([[1, 0, 0]] + [[1, 1, -1]] * 5)
    result = popular(m, 0, n=5, rng=random.Random(0))
    assert result == [(1, 5 / 6), (2, 0.0)]  # score: likes / max likes (movie 0 has 6)


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
    assert all(i < 4 for i, _ in a)  # top 2 * n = 4 pool
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
    result = recommend_with_strategy(m, 0, min_overlap=5, min_user_ratings=5)
    assert result.strategy == "collaborative"
    assert [i for i, _ in result.items] == [5]


def test_no_neighbors_falls_back():
    rows = [[1, 1, 1, 1, 1, 0, 0]] + [[-1, -1, -1, -1, -1, 1, 1]] * 6
    result = recommend_with_strategy(make(rows), 0, rng=random.Random(0))
    assert result.strategy == "fallback"
    assert not {0, 1, 2, 3, 4} & {i for i, _ in result.items}


def test_pop_penalty_reaches_recommend_on_collaborative_path():
    import pytest

    rows = [[1, 1, 1, 1, 1, 0, 0]] + [[1, 1, 1, 1, 1, 1, 0]] * 3
    with pytest.raises(ValueError, match="pop_penalty"):
        recommend_with_strategy(make(rows), 0, min_overlap=5, min_user_ratings=5, pop_penalty=-1.0)
    default = recommend_with_strategy(make(rows), 0, min_overlap=5, min_user_ratings=5)
    assert default == recommend_with_strategy(
        make(rows), 0, min_overlap=5, min_user_ratings=5, pop_penalty=1.0
    )


def like_count_matrix() -> csr_matrix:
    """Movie 0: 30 likes of 100; movie 1: 5 of 5; movie 2: 30 of 30. User 0 rated nothing."""
    rows = [[0, 0, 0]]
    for i in range(1, 101):
        rows.append([1 if i <= 30 else -1, 1 if i <= 5 else 0, 1 if i <= 30 else 0])
    return make(rows)


def test_popular_ranks_by_like_count_not_share():
    result = popular(like_count_matrix(), 0, n=3, pool_factor=1)
    assert [i for i, _ in result][-1] == 1  # 5 likes of 5 ranks below 30 likes of 100


def test_popular_ties_prefer_higher_share_then_lower_index():
    m = like_count_matrix()
    # movies 0 and 2 both have 30 likes; movie 2 has the higher share, so it wins a single slot
    assert [i for i, _ in popular(m, 0, n=1, pool_factor=1)] == [2]
    # the output order is likes descending, ties by movie index
    assert [i for i, _ in popular(m, 0, n=3, pool_factor=1)] == [0, 2, 1]


def test_popular_pool_factor_one_is_exact_top_and_deterministic():
    m = make([[0] * 10] + crowd())
    for seed in range(5):
        result = popular(m, 0, n=3, pool_factor=1, rng=random.Random(seed))
        assert [i for i, _ in result] == [0, 1, 2]


def test_popular_scores_are_in_unit_interval():
    m = make([[0] * 10] + crowd())
    scores = [s for _, s in popular(m, 0, n=10, rng=random.Random(0))]
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert max(scores) == 1.0
    assert popular(make([[0, 0], [-1, -1]]), 0, n=2) == [(0, 0.0), (1, 0.0)]


def test_strategy_switches_at_five_ratings():
    neighbours = [[1] * 6 + [1]] * 3
    four = make([[1] * 4 + [0, 0, 0]] + neighbours)
    assert recommend_with_strategy(four, 0, min_overlap=1).strategy == "fallback"
    five = make([[1] * 5 + [0, 0]] + neighbours)
    assert recommend_with_strategy(five, 0, min_overlap=1).strategy == "collaborative"


def test_strategy_passes_pool_factor_and_defaults_to_exact_top():
    big = make([[0] * 10] + crowd())
    for seed in range(5):
        default = recommend_with_strategy(big, 0, n=2, rng=random.Random(seed))
        assert [i for i, _ in default.items] == [0, 1]
    wide = {
        tuple(
            i
            for i, _ in recommend_with_strategy(
                big, 0, n=2, fallback_pool_factor=4, rng=random.Random(seed)
            ).items
        )
        for seed in range(20)
    }
    assert len(wide) > 1
