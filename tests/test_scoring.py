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


def test_weighted_norm_with_mixed_ratings():
    # Neighbours 1 and 2 disagree on movie 3 and have different similarities.
    m = make([[1, 1, 1, 0], [1, 1, 1, 1], [1, 1, 0, -1]])
    sim1, sim2 = math.sqrt(3) / 2, 2 / 3
    (idx, score) = recommend(m, 0, min_overlap=2, lam=0.0)[0]
    assert idx == 3
    assert score == pytest.approx((sim1 - sim2) / (sim1 + sim2) / math.log(3))


def test_pop_penalty_default_matches_explicit_one():
    m = likes_matrix([1, 2, 3, 4, 5, 6, 7], [1, 2, 3, 5, 7, 8, 9])
    assert recommend(m, 0, min_overlap=5) == recommend(m, 0, min_overlap=5, pop_penalty=1.0)


def test_pop_penalty_zero_scores_popular_movie_higher_than_two():
    m = likes_matrix([1, 2, 3], [1, 2, 3, 4], [1, 2, 3, 4], [4], [4], cols=5)
    low = dict(recommend(m, 0, min_overlap=3, pop_penalty=0.0))
    high = dict(recommend(m, 0, min_overlap=3, pop_penalty=2.0))
    assert low[3] > high[3]


def test_pop_penalty_negative_raises():
    m = likes_matrix([1, 2, 3], [1, 2, 3, 4])
    with pytest.raises(ValueError, match="pop_penalty"):
        recommend(m, 0, min_overlap=3, pop_penalty=-0.5)


def test_significance_reaches_find_neighbors():
    cols = 70
    user = [1 if j < 5 else 0 for j in range(cols)]
    one_overlap = [1 if j in (0, 5) else 0 for j in range(cols)]  # cosine 0.316, overlap 1
    five_overlap = [1 if j < 5 or j == 6 or j >= 10 else 0 for j in range(cols)]  # cosine ~0.29
    m = make([user, one_overlap, five_overlap])
    plain = recommend(m, 0, k=1, min_overlap=1, lam=0.0)
    assert [i for i, _ in plain] == [5]
    assert recommend(m, 0, k=1, min_overlap=1, lam=0.0, significance=0) == plain
    weighted = {i for i, _ in recommend(m, 0, k=1, min_overlap=1, lam=0.0, significance=5)}
    assert 5 not in weighted and 6 in weighted


def test_significance_negative_raises():
    m = likes_matrix([1, 2, 3], [1, 2, 3, 4])
    with pytest.raises(ValueError, match="significance"):
        recommend(m, 0, min_overlap=1, significance=-1)


def twin_matrix() -> csr_matrix:
    """User 0 likes 1..10; user 1 (twin) 1..8 and 11, 12; users 2..6 like 1 and 13 only."""
    return likes_matrix(
        list(range(1, 11)),
        [*range(1, 9), 11, 12],
        *([1, 13] for _ in range(5)),
        cols=13,
    )


def test_defaults_are_the_original_formula():
    m = twin_matrix()
    assert recommend(m, 0, min_overlap=1) == recommend(
        m, 0, min_overlap=1, sim_power=1.0, shrink="count"
    )


def test_count_with_power_one_matches_hand_computed_scores():
    m = make([[1, 1, 0], [1, 1, 1]])
    score = dict(recommend(m, 0, min_overlap=1, lam=1.0, pop_penalty=0.0))[2]
    assert score == pytest.approx(1.0 * 1 / (1 + 1.0))


def test_mass_shrink_uses_similarity_sum():
    m = make([[1, 1, 0], [1, 1, 1]])
    sim = 2 / math.sqrt(2 * 3)  # cosine of the only neighbour
    score = dict(recommend(m, 0, min_overlap=1, pop_penalty=0.0, shrink="mass", mass_lambda=0.5))[2]
    assert score == pytest.approx(sim / (sim + 0.5))


def test_sim_power_enters_mass_and_norm():
    m = make([[1, 1, 0], [1, 0, 1]])
    sim = 0.5  # cosine of [1, 1, 0] and [1, 0, 1]
    got = dict(recommend(m, 0, min_overlap=1, pop_penalty=0.0, shrink="mass", sim_power=2.0))[2]
    assert got == pytest.approx(sim**2 / (sim**2 + 0.5))
    # a like and a dislike from equally similar neighbours cancel in the norm
    mixed = make([[1, 1, 0], [1, 0, 1], [1, 0, -1]])
    s = dict(recommend(mixed, 0, min_overlap=1, pop_penalty=0.0, shrink="mass", sim_power=2.0))
    assert s[2] == pytest.approx(0.0, abs=1e-12)


def test_twin_movies_lead_with_mass_and_not_with_count():
    m = twin_matrix()
    top_mass = [i for i, _ in recommend(m, 0, n=2, k=150, min_overlap=1, lam=40.0, shrink="mass")]
    assert set(top_mass) == {10, 11}  # movies 11 and 12
    top_count = [
        i
        for i, _ in recommend(
            m, 0, n=2, k=150, min_overlap=1, lam=40.0, shrink="count", sim_power=1.0
        )
    ]
    assert set(top_count) != {10, 11}


@pytest.mark.parametrize("kwargs", [{"sim_power": 0.0}, {"mass_lambda": -1.0}, {"shrink": "sum"}])
def test_invalid_scoring_parameters_raise(kwargs):
    with pytest.raises(ValueError):
        recommend(twin_matrix(), 0, **kwargs)
