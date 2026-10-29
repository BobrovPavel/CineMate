import math

import numpy as np
import pytest

from cinemate.recommender.taste import (
    ANIMATION,
    DECADE,
    GENRE,
    LANGUAGE,
    TYPE,
    MovieFeatures,
    build_profile,
    build_taste_data,
    diversify,
    movie_groups,
    rerank,
    taste_reason,
    taste_score,
    zscore,
)


def test_movie_groups_cover_every_kind():
    groups = movie_groups(
        MovieFeatures(genres=(16, 18), kind="tv", language="ja", year=1997, collection_id=5)
    )
    assert groups == (
        ((GENRE, 16), (GENRE, 18)),
        ((TYPE, "tv"),),
        ((ANIMATION, "animation"), (ANIMATION, "anime")),
        ((DECADE, 1990),),
        ((LANGUAGE, "ja"),),
    )


def test_animation_without_japanese_is_not_anime_and_unknown_fields_are_skipped():
    assert movie_groups(MovieFeatures(genres=(16,))) == (
        ((GENRE, 16),),
        ((ANIMATION, "animation"),),
    )
    assert movie_groups(MovieFeatures()) == ()


def _data(features, likes=None):
    likes = np.array(likes if likes is not None else [1] * len(features))
    return build_taste_data(features, likes)


def test_base_is_the_share_of_pool_likes():
    data = _data([MovieFeatures(genres=(14,)), MovieFeatures(genres=(18,))], [3, 1])
    assert data.base[(GENRE, 14)] == pytest.approx(0.75)
    assert data.base[(GENRE, 18)] == pytest.approx(0.25)


def test_primary_genre_is_the_rarest_one():
    data = _data([MovieFeatures(genres=(14,)), MovieFeatures(genres=(18, 14))], [1, 5])
    # 14 holds 6/6 of the likes, 18 only 5/6
    assert data.primary_genre == [14, 18]


def test_contribution_follows_the_formula():
    data = _data([MovieFeatures(genres=(14,)), MovieFeatures(genres=(18,))], [1, 1])
    profile = build_profile(data, liked=[0, 0, 0], disliked=[0])
    liked, disliked = 3.0, 1.0
    quality = (liked - disliked) / (liked + disliked + 2)
    expected = 3 * 0.5  # n_likes * base
    interest = math.log((liked + 1) / (expected + 1))
    assert profile.contribution((GENRE, 14)) == pytest.approx(quality + 0.5 * interest)


def test_smoothing_keeps_a_single_like_modest():
    data = _data([MovieFeatures(genres=(14,))])
    profile = build_profile(data, liked=[0])
    assert profile.contribution((GENRE, 14)) < 1 / 3 + 0.5 * math.log(2)


def test_not_interested_is_half_a_dislike():
    data = _data([MovieFeatures(genres=(14,)), MovieFeatures(genres=(18,))])
    soft = build_profile(data, liked=[1], not_interested=[0])
    hard = build_profile(data, liked=[1], disliked=[0])
    assert soft.dislikes[(GENRE, 14)] == 0.5
    assert hard.dislikes[(GENRE, 14)] == 1.0
    assert soft.contribution((GENRE, 14)) > hard.contribution((GENRE, 14))
    assert soft.n_likes == 1


def test_interest_pushes_down_features_the_user_never_likes():
    movies = [MovieFeatures(genres=(18,), kind="movie"), MovieFeatures(genres=(16,), kind="tv")]
    data = _data(movies)
    profile = build_profile(data, liked=[0, 0, 0, 0])
    assert taste_score(profile, data.groups[0]) > 0 > taste_score(profile, data.groups[1])


def test_movie_without_features_scores_zero():
    data = _data([MovieFeatures()])
    assert taste_score(build_profile(data, liked=[0]), data.groups[0]) == 0.0


def test_score_averages_inside_and_across_groups():
    data = _data([MovieFeatures(genres=(14, 18), kind="movie")])
    profile = build_profile(data, liked=[0])
    genre = (profile.contribution((GENRE, 14)) + profile.contribution((GENRE, 18))) / 2
    kind = profile.contribution((TYPE, "movie"))
    assert taste_score(profile, data.groups[0]) == pytest.approx((genre + kind) / 2)


def test_zscore_of_constant_is_zero():
    assert zscore([2.0, 2.0, 2.0]).tolist() == [0.0, 0.0, 0.0]
    assert zscore([]).size == 0


def test_rerank_weight_zero_keeps_cf_order_and_weight_moves_taste_up():
    cf = [3.0, 2.0, 1.0]
    taste = [0.0, 0.0, 5.0]
    assert rerank(cf, taste, 0) == [0, 1, 2]
    assert rerank(cf, taste, 5)[0] == 2


def test_diversify_limits_a_genre_in_every_window():
    genres = [1] * 8 + [2] * 4 + [3] * 4
    order = diversify(list(range(16)), lambda i: genres[i], lambda i: None, window=10, max_genre=4)
    assert sorted(order) == list(range(16))
    for start in range(len(order) - 9):
        window = [genres[i] for i in order[start : start + 10]]
        assert window.count(1) <= 4
    assert order[:4] == [0, 1, 2, 3]  # order of the rest is kept


def test_diversify_limits_a_collection():
    collections = [7, 7, 7, 7, None, None, None, None]
    order = diversify(list(range(8)), lambda i: None, lambda i: collections[i])
    assert [collections[i] for i in order[:5]].count(7) <= 2
    assert order[:2] == [0, 1]


def test_diversify_keeps_everything_when_limits_cannot_hold():
    order = diversify(list(range(6)), lambda i: 1, lambda i: None, max_genre=2)
    assert order == list(range(6))


def test_reason_needs_a_sure_profile():
    movies = [MovieFeatures(genres=(14,)), MovieFeatures(genres=(18,))]
    data = _data(movies)
    groups = data.groups[0]
    few = build_profile(data, liked=[0, 0])
    assert taste_reason(few, groups) is None
    sure = build_profile(data, liked=[0, 0, 0, 0, 1])
    assert taste_reason(sure, groups) == (GENRE, 14)
    assert taste_reason(sure, groups, kinds=[TYPE]) is None
