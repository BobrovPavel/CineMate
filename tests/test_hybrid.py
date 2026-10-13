import math
import random

import pytest
from scipy.sparse import csr_matrix

from cinemate.recommender.hybrid import recommend_hybrid, recommend_hybrid_detailed
from cinemate.recommender.scoring import recommend
from cinemate.recommender.strategy import recommend_with_strategy


def make(rows: list[list[int]]) -> csr_matrix:
    return csr_matrix(rows, dtype="int8")


# Movies 0-1 are rated by the user; 2 is liked by 3 users (most popular), 3 by 2, 4 by 1.
# User 1 is the neighbour (shares movies 0-1) and likes 3 and 4.
POP_MATRIX = make(
    [
        [1, 1, 0, 0, 0],
        [1, 1, 0, 1, 1],
        [0, 0, 1, 1, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0],
    ]
)


def test_no_ratings_gives_popularity_order():
    m = make([[0, 0, 0, 0], [1, 0, 1, 1], [0, 0, 1, 1], [0, 0, 1, 0]])
    items = recommend_hybrid(m, 0, n=4)
    assert [i for i, _ in items] == [2, 3, 0, 1]
    assert items[0][1] == pytest.approx(1.0)  # 3 likes / max 3
    assert items[1][1] == pytest.approx(2 / 3)


def test_full_beta_orders_by_cf_scaled():
    # n_inf = 2 >= blend_full_at -> beta = 1: only neighbour-based scores count.
    items = recommend_hybrid(POP_MATRIX, 0, n=3, lam=0.0, blend_full_at=2)
    # Neighbour (user 1) rated 3 and 4 with +1: cf = 1 for both, ties by index; 2 has no neighbour.
    assert items == [(3, 1.0), (4, 1.0), (2, 0.0)]


def test_intermediate_beta_manual_example():
    # n_inf = 2, blend_full_at = 4 -> beta = 0.5. lam = 1, one neighbour: cf = 1 * 1/(1+1) = .5,
    # cf_scaled = 1 for movies 3 and 4. pop: likes 2:3, 3:2, 4:1 of max 3.
    items = dict(recommend_hybrid(POP_MATRIX, 0, n=3, lam=1.0, blend_full_at=4))
    assert items[2] == pytest.approx(0.5 * 1.0)
    assert items[3] == pytest.approx(0.5 * 2 / 3 + 0.5)
    assert items[4] == pytest.approx(0.5 * 1 / 3 + 0.5)
    order = [i for i, _ in recommend_hybrid(POP_MATRIX, 0, n=3, lam=1.0, blend_full_at=4)]
    assert order == [3, 4, 2]


def test_negative_cf_is_clipped_to_zero():
    m = make([[1, 1, 0, 0], [1, 1, -1, 1]])
    items = dict(recommend_hybrid(m, 0, n=2, lam=0.0, blend_full_at=2))
    assert items[2] == 0.0
    assert items[3] == pytest.approx(1.0)


def test_no_neighbors_keeps_likes_order():
    m = make([[1, 0, 0, 0], [0, 0, 1, 1], [0, 0, 1, 0]])
    result = recommend_hybrid_detailed(m, 0, n=3, blend_full_at=2)
    assert not result.has_neighbors
    assert [i for i, _ in result.items] == [2, 3, 1]


def test_rated_movies_are_excluded_including_dislikes():
    m = make([[1, -1, 0, 0], [1, -1, 1, 1]])
    assert {i for i, _ in recommend_hybrid(m, 0, n=10)} == {2, 3}


def test_zero_entries_do_not_count_as_ratings():
    m = make([[1, 1, 0, 0], [1, 1, 1, 0]])
    assert recommend_hybrid_detailed(m, 0, blend_full_at=4).beta == 0.5


def test_no_likes_at_all_gives_zero_scores():
    m = make([[0, 0, 0], [0, 0, 0]])
    assert recommend_hybrid(m, 0, n=3) == [(0, 0.0), (1, 0.0), (2, 0.0)]


def test_parameter_errors():
    with pytest.raises(ValueError, match="blend_full_at"):
        recommend_hybrid(POP_MATRIX, 0, blend_full_at=0)
    with pytest.raises(ValueError, match="blend_full_at"):
        recommend_hybrid(POP_MATRIX, 0, blend_full_at=-3)
    with pytest.raises(ValueError, match="blend_full_at"):
        recommend_hybrid(POP_MATRIX, 0, blend_full_at=math.nan)
    with pytest.raises(ValueError, match="significance"):
        recommend_hybrid(POP_MATRIX, 0, significance=-1)
    assert recommend_hybrid(POP_MATRIX, 0, n=0) == []


def test_strategy_label_follows_beta_and_neighbors():
    # beta = 2/4 = 0.5 with neighbours -> collaborative
    rec = recommend_with_strategy(POP_MATRIX, 0, blend_full_at=4, min_overlap=1)
    assert rec.strategy == "collaborative"
    # beta = 2/5 < 0.5 -> fallback
    rec = recommend_with_strategy(POP_MATRIX, 0, blend_full_at=5, min_overlap=1)
    assert rec.strategy == "fallback"
    # beta = 1 but no neighbours -> fallback
    lonely = make([[1, 0, 0], [0, 1, 1]])
    assert recommend_with_strategy(lonely, 0, blend_full_at=1).strategy == "fallback"


def test_strategy_hybrid_replaces_threshold_logic():
    rec = recommend_with_strategy(POP_MATRIX, 0, blend_full_at=2, min_overlap=1, lam=1.0)
    assert rec.items == recommend_hybrid(
        POP_MATRIX, 0, k=40, min_overlap=1, lam=1.0, blend_full_at=2
    )


def test_strategy_disabled_hybrid_keeps_old_behavior():
    args = {"min_overlap": 1, "rng": random.Random(0)}
    assert recommend_with_strategy(POP_MATRIX, 0, **args) == recommend_with_strategy(
        POP_MATRIX, 0, blend_full_at=0.0, min_overlap=1, rng=random.Random(0)
    )


def test_recommend_unchanged_by_refactor():
    m = make([[1, 1, 1, 0, 0], [1, 1, 1, 1, -1], [1, 1, 1, 1, 0]])
    scores = dict(recommend(m, 0, min_overlap=3, lam=0.0, pop_penalty=0.0))
    assert scores[3] == pytest.approx(1.0)
    assert scores[4] == pytest.approx(-1.0)
