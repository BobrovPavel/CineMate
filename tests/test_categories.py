import numpy as np
from scipy.sparse import csr_matrix

from cinemate.recommender.categories import (
    CategoryStats,
    CategoryThresholds,
    category_stats,
    column_categories,
    demote,
    dislike_similarity,
    triggered_categories,
)
from cinemate.recommender.taste import MovieFeatures, build_taste_data, rerank

ANIMATION = 16


def data_for(features):
    return build_taste_data(features, np.ones(len(features)))


def test_demote_puts_hidden_right_after_the_twentieth_in_order():
    items = list(range(30))
    hidden = {1, 5, 25}
    out = demote(items, lambda i: i in hidden)
    visible = [i for i in items if i not in hidden]
    assert out == visible[:20] + [1, 5, 25] + visible[20:]
    assert sorted(out) == items


def test_demote_with_few_visible_items_keeps_hidden_after_them():
    assert demote([1, 2, 3, 4], lambda i: i in (1, 2), keep=20) == [3, 4, 1, 2]


def test_demote_without_hidden_changes_nothing():
    assert demote([3, 1, 2], lambda _: False) == [3, 1, 2]


def test_column_categories_lists_collection_studios_genres_and_anime():
    data = data_for(
        [
            MovieFeatures(genres=(ANIMATION, 35), language="ja", collection_id=7, companies=(1,)),
            MovieFeatures(genres=(35,), language="en"),
        ]
    )
    assert set(column_categories(data, 0, 150)) == {
        ("collection", "7"),
        ("studio", "1"),
        ("genre", "16"),
        ("genre", "35"),
        ("anime", "anime"),
    }
    assert set(column_categories(data, 1, 150)) == {("genre", "35")}


def test_anime_needs_japanese_original_language():
    data = data_for([MovieFeatures(genres=(ANIMATION,), language="en")])
    assert ("anime", "anime") not in column_categories(data, 0, 150)


def test_big_studio_is_not_recognisable_small_one_is():
    # studio 1 has 3 columns, studio 2 has 1
    features = [MovieFeatures(companies=(1,))] * 3 + [MovieFeatures(companies=(2,))]
    data = data_for(features)
    assert data.company_sizes == {1: 3, 2: 1}
    assert ("studio", "1") not in column_categories(data, 0, 2)
    assert ("studio", "1") in column_categories(data, 0, 3)
    assert ("studio", "2") in column_categories(data, 3, 2)


def test_triggers_by_kind_thresholds_and_a_like_cancels():
    data = data_for([MovieFeatures(genres=(35,), collection_id=1, companies=(1,))] * 6)
    thresholds = CategoryThresholds()

    def triggered(values):
        row = csr_matrix(np.array([values], dtype=np.int8))
        return triggered_categories(category_stats(data, row, 150), thresholds)

    assert triggered([-1, -1, 0, 0, 0, 0]) == set()
    assert triggered([-1, -1, -1, 0, 0, 0]) == {("collection", "1"), ("studio", "1")}
    assert triggered([-1] * 5 + [0]) == {("collection", "1"), ("studio", "1"), ("genre", "35")}
    assert triggered([-1, -1, -1, -1, -1, 1]) == set()


def test_stats_count_rated_movies():
    data = data_for([MovieFeatures(collection_id=1)] * 3)
    row = csr_matrix(np.array([[-1, -1, 1]], dtype=np.int8))
    assert category_stats(data, row, 150) == {("collection", "1"): CategoryStats(1, 2)}
    assert category_stats(data, row, 150)[("collection", "1")].rated == 3


def test_dislike_similarity_is_the_max_cosine_to_disliked_columns():
    # users x movies; column 0 candidate, 1 candidate, 2 and 3 disliked
    matrix = csr_matrix(
        np.array(
            [
                [1, 0, 1, 0],
                [1, 0, 1, 0],
                [0, 1, 0, 1],
                [0, 1, 0, 0],
            ],
            dtype=np.int8,
        )
    )
    sims = dislike_similarity(matrix, [0, 1], [2, 3])
    assert np.allclose(sims, [1.0, 1 / np.sqrt(2)])


def test_dislike_similarity_without_dislikes_is_zero():
    matrix = csr_matrix(np.ones((2, 3), dtype=np.int8))
    assert dislike_similarity(matrix, [0, 1], []).tolist() == [0.0, 0.0]


def test_rerank_penalty_lowers_similar_candidates():
    # equal CF and taste: the penalty alone decides
    assert rerank([1, 1, 1], [0, 0, 0], 0.5, penalties=[0.9, 0.1, 0.5], penalty_weight=0.5) == [
        1,
        2,
        0,
    ]
    assert rerank([1, 1, 1], [0, 0, 0], 0.5, penalties=[0.9, 0.1, 0.5], penalty_weight=0) == [
        0,
        1,
        2,
    ]
