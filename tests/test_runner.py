import pytest

from cinemate.binarize import MovieLensBinarizer
from cinemate.config import RecommenderSettings
from cinemate.evaluation.runner import (
    evaluate,
    popular_baseline,
    popular_by_likes,
    popular_by_share,
)
from cinemate.movielens import Rating
from cinemate.recommender.matrix import build_matrix
from cinemate.recommender.taste import MovieFeatures

B = MovieLensBinarizer()


def likes(user: int, *movies: int) -> list[Rating]:
    return [Rating(user, m, 5.0) for m in movies]


def make_train() -> list[Rating]:
    # users 1 and 2 share movies 1-5; user 2 also likes 6 and 7; user 3 is unrelated.
    train = likes(1, 1, 2, 3, 4, 5) + likes(2, 1, 2, 3, 4, 5, 6, 7) + likes(3, 8, 9, 10)
    train += [Rating(4, m, 1.0) for m in (6, 7, 8, 9, 10)]  # dislikes raise the denominator
    return train


def run(test, **kw):
    kw.setdefault("min_overlap", 3)
    kw.setdefault("top_n", 2)
    return evaluate(make_train(), test, B, **kw)


def test_known_values():
    result = run(likes(1, 6, 7))
    assert result.n_users == 1
    assert result.cf.precision_at_k == 1.0
    assert result.cf.recall_at_k == 1.0
    assert result.cf.hit_rate_at_k == 1.0
    assert result.baseline.precision_at_k == 0.0
    assert result.baseline.hit_rate_at_k == 0.0
    assert 0.0 <= result.baseline.recall_at_k <= 1.0


def test_baseline_is_deterministic_and_excludes_train():
    matrix = build_matrix(make_train(), B)
    rated = {0, 1}
    first = popular_baseline(matrix.matrix, rated, n=3, min_ratings=1)
    assert first == popular_baseline(matrix.matrix, rated, n=3, min_ratings=1)
    assert not set(first) & rated
    assert popular_baseline(matrix.matrix, rated, n=0) == []


def test_users_without_test_likes_are_skipped():
    test = likes(1, 6) + [Rating(2, 8, 1.0), Rating(3, 8, 3.0)] + likes(99, 6)
    result = run(test)
    assert result.n_users == 1  # user 2 has only a dislike, 3 a discarded score, 99 is unknown


def test_train_items_never_recommended():
    # user 1 "tests" on movies already rated in train: nothing may be recommended from them
    result = run(likes(1, 1, 2, 3))
    assert result.cf.precision_at_k == 0.0
    assert result.baseline.precision_at_k == 0.0


def test_unseen_test_movie_counts_in_recall_denominator():
    result = run(likes(1, 6, 999))
    assert result.cf.recall_at_k == pytest.approx(0.5)


def test_no_evaluable_users():
    result = run([])
    assert result.n_users == 0
    assert result.cf.precision_at_k == 0.0
    assert result.baseline.coverage == 0.0


def test_deterministic():
    test = likes(1, 6, 7) + likes(3, 8)
    assert run(test) == run(test)


def test_baseline_values_through_evaluate():
    # movie 1: 5/5 likes, movie 2: 4/5, movie 3: 0/5, movie 4: liked by all (user 20 rated it).
    train = likes(20, 4)
    for u in range(10, 15):
        train += likes(u, 1, 4) + [Rating(u, 2, 5.0 if u != 14 else 1.0), Rating(u, 3, 1.0)]
    result = evaluate(train, likes(20, 1, 2), B, min_overlap=5, top_n=2)
    assert result.n_users == 1
    assert result.baseline.precision_at_k == 1.0  # picks [1, 2]; movie 4 is excluded (in train)
    assert result.baseline.recall_at_k == 1.0
    assert result.baseline.hit_rate_at_k == 1.0
    assert result.cf.hit_rate_at_k == 0.0
    assert result.baseline.coverage == pytest.approx(0.5)  # 2 of 4 train movies
    assert result.baseline.mean_popularity == pytest.approx((5 / 6 + 4 / 6) / 2)
    assert result.cf.precision_at_k == 0.0  # no neighbours with enough overlap
    assert result.cf.coverage == 0.0


def _manual_matrix():
    # likes per movie (index = movie id - 1): m1: 4 of 4, m2: 3 of 3, m3: 3 of 6, m4: 3 of 3,
    # m5: 2 of 2. Users 1-4 like m1; 1-3 like m2, m4; 1-3 like m3 and 4-6 dislike it.
    train = []
    for u in (1, 2, 3, 4):
        train += likes(u, 1)
    for u in (1, 2, 3):
        train += likes(u, 2, 3, 4)
    for u in (4, 5, 6):
        train.append(Rating(u, 3, 1.0))
    train += likes(5, 5) + likes(6, 5)
    return build_matrix(train, B).matrix


def test_popular_by_likes_order_ties_and_exclude():
    matrix = _manual_matrix()
    # likes: m1=4, m2=3, m3=3, m4=3, m5=2 -> ties broken by lower index
    assert popular_by_likes(matrix, set(), n=5) == [0, 1, 2, 3, 4]
    assert popular_by_likes(matrix, {0, 2}, n=2) == [1, 3]
    assert popular_by_likes(matrix, set(), n=0) == []
    assert popular_by_likes(matrix, set(), n=10) == [0, 1, 2, 3, 4]


def test_popular_by_share_threshold_exclude_and_ties():
    matrix = _manual_matrix()
    # shares: m1 1.0 (4), m2 1.0 (3), m3 0.5 (6), m4 1.0 (3), m5 1.0 (2)
    assert popular_by_share(matrix, set(), n=5, min_ratings=1) == [0, 1, 3, 4, 2]
    assert popular_by_share(matrix, set(), n=5, min_ratings=3) == [0, 1, 3, 2]
    assert popular_by_share(matrix, set(), n=5, min_ratings=5) == [2]
    assert popular_by_share(matrix, {0}, n=2, min_ratings=3) == [1, 3]
    assert popular_by_share(matrix, set(), n=5, min_ratings=20) == []
    assert popular_by_share(matrix, set(), n=0, min_ratings=1) == []


def test_evaluate_has_all_baselines():
    result = run(likes(1, 6, 7))
    assert set(result.baselines) == {
        "popular",
        "popular_likes",
        "popular_share_20",
        "popular_share_50",
        "product",
        "item_based",
    }
    assert result.baseline is result.baselines["popular"]
    # no movie reaches 20 ratings in this tiny dataset -> empty lists, zero metrics
    assert result.baselines["popular_share_20"].precision_at_k == 0.0
    assert result.baselines["popular_likes"].coverage > 0.0


def test_evaluate_pop_penalty_validated_and_passed_through():
    with pytest.raises(ValueError, match="pop_penalty"):
        run(likes(1, 6, 7), pop_penalty=-1.0)
    assert run(likes(1, 6, 7), pop_penalty=1.0) == run(likes(1, 6, 7))


def cold_data():
    """20 users: even users like movies 1-6, odd users like 7-12; each skips one (its test like)."""
    train, test = [], []
    for u in range(1, 21):
        base = (1, 2, 3, 4, 5, 6) if u % 2 == 0 else (7, 8, 9, 10, 11, 12)
        held_out = base[(u // 2) % 6]
        train += likes(u, *(m for m in base if m != held_out))
        test += likes(u, held_out)
    return train, test


def test_new_user_ratings_must_be_positive():
    train, test = cold_data()
    with pytest.raises(ValueError):
        evaluate(train, test, B, new_user_ratings=0)


def test_cold_start_evaluates_only_new_users_and_is_deterministic():
    train, test = cold_data()
    kw = {"min_overlap": 1, "top_n": 3, "new_user_ratings": 3, "seed": 4}
    first = evaluate(train, test, B, **kw)
    assert first.new_user_ratings == 3
    assert first.n_users == 10  # half of the 20 users
    assert evaluate(train, test, B, **kw) == first
    assert "product" in first.baselines


def test_cold_start_truncates_matrix_and_hides_dropped_ratings(monkeypatch):
    from cinemate.evaluation import runner

    train, test = cold_data()
    captured = {}
    real_build = runner.build_matrix

    def spy(ratings, binarizer):
        captured["train"] = list(ratings)
        return real_build(captured["train"], binarizer)

    monkeypatch.setattr(runner, "build_matrix", spy)
    result = evaluate(train, test, B, min_overlap=1, top_n=1, new_user_ratings=3, seed=1)
    counts = {}
    for r in captured["train"]:
        counts[r.user_id] = counts.get(r.user_id, 0) + 1
    assert sorted(counts.values()) == [3] * 10 + [5] * 10
    assert result.n_users == 10
    # A new user keeps 3 of 5 train ratings; the 2 dropped ones are still "seen" and must not
    # take the single slot, so the held-out test like is the only possible recommendation.
    assert result.cf.precision_at_k == 1.0
    # established users are neighbours only: evaluating them would give n_users == 20
    assert result.n_users < 20


def test_product_strategy_depends_on_new_user_ratings(monkeypatch):
    from cinemate.evaluation import runner

    train, test = cold_data()
    strategies = []
    real = runner.recommend_with_strategy

    def spy(*args, **kwargs):
        rec = real(*args, **kwargs)
        strategies.append(rec.strategy)
        return rec

    monkeypatch.setattr(runner, "recommend_with_strategy", spy)
    five = RecommenderSettings(min_user_ratings=5)
    evaluate(train, test, B, min_overlap=1, top_n=3, new_user_ratings=3, seed=2, settings=five)
    assert set(strategies) == {"fallback"}  # fewer than 5 ratings
    strategies.clear()
    evaluate(train, test, B, min_overlap=1, top_n=3, new_user_ratings=4, seed=2, settings=five)
    assert set(strategies) == {"fallback"}  # still below MIN_USER_RATINGS
    strategies.clear()
    evaluate(train, test, B, min_overlap=1, top_n=3, settings=five)
    assert "collaborative" in strategies  # full histories: 5 ratings, CF


def test_without_new_user_ratings_all_users_are_evaluated():
    train, test = cold_data()
    result = evaluate(train, test, B, min_overlap=1, top_n=3)
    assert result.n_users == 20
    assert result.new_user_ratings is None


def test_cold_start_uses_only_usable_ratings_and_eligible_users(monkeypatch):
    from cinemate.evaluation import runner

    train, test = cold_data()
    # user 99 has neutral ratings only (3.0): never eligible; user 98 has 2 usable ratings < N
    train += [Rating(99, m, 3.0) for m in range(1, 8)]
    train += [Rating(98, 1, 5.0), Rating(98, 2, 5.0)] + [Rating(98, m, 3.0) for m in (3, 4, 5)]
    # neutral ratings mixed into regular users must not be picked as "kept"
    train += [Rating(u, 12 + u, 3.0) for u in range(1, 21)]
    test += likes(98, 3) + likes(99, 1)
    captured = {}
    real_build = runner.build_matrix

    def spy(ratings, binarizer):
        captured["train"] = list(ratings)
        return real_build(captured["train"], binarizer)

    monkeypatch.setattr(runner, "build_matrix", spy)
    result = evaluate(train, test, B, min_overlap=1, top_n=1, new_user_ratings=3, seed=3)
    counts = {}
    for r in captured["train"]:
        counts[r.user_id] = counts.get(r.user_id, 0) + 1
    new = [u for u in range(1, 21) if counts[u] < 6]
    assert len(new) == 10 and result.n_users == 10
    for u in new:
        kept = [r for r in captured["train"] if r.user_id == u]
        assert len(kept) == 3 and all(B.binarize(r.score) is not None for r in kept)
    assert counts[98] == 5 and counts[99] == 7  # ineligible users stay untouched, not evaluated


def test_product_follows_min_user_ratings():
    train, test = cold_data()
    kw = {"min_overlap": 1, "top_n": 3, "seed": 2}
    cf_like = evaluate(train, test, B, settings=RecommenderSettings(min_user_ratings=1), **kw)
    fallback = evaluate(
        train,
        test,
        B,
        settings=RecommenderSettings(min_user_ratings=10**6, fallback_pool_factor=1),
        **kw,
    )
    assert cf_like.baselines["product"] != fallback.baselines["product"]
    # with an unreachable threshold the product row is the exact popular-by-likes top
    assert fallback.baselines["product"] == fallback.baselines["popular_likes"]


def onboarding_train():
    """Users 1-8 rate cards 1-3 (reversed list order), users 9-10 only rarely rated movies 4-6."""
    train = []
    for u in range(1, 9):
        # movie 1: 4 likes / 4 dislikes, movie 2: 6 / 2, movie 3: 8 / 0 -> card order 1, 2, 3
        scores = {1: u <= 4, 2: u <= 6, 3: True}
        train += [Rating(u, m, 5.0 if scores[m] else 1.0) for m in (3, 2, 1)]
    train += likes(9, 4, 5, 6, 1) + likes(10, 4, 5, 6)
    return train


def test_onboarding_pick_keeps_first_cards_in_order_and_skips_ineligible(monkeypatch):
    from cinemate.evaluation import runner

    monkeypatch.setattr(runner, "ONBOARDING_POOL", 3)
    train = onboarding_train()
    reduced, new = runner._truncate_new_users(train, 2, 0, B, "onboarding")
    assert len(new) == 4 and new <= set(range(1, 9))  # users 9 and 10 have < 2 cards
    for u in new:
        assert {r.movie_id for r in reduced if r.user_id == u} == {1, 2}
    for u in set(range(1, 11)) - new:
        assert [r for r in reduced if r.user_id == u] == [r for r in train if r.user_id == u]
    assert runner._truncate_new_users(train, 2, 0, B, "onboarding") == (reduced, new)


def test_onboarding_pick_keeps_dropped_ratings_as_seen():
    train, test = cold_data()
    kw = {"min_overlap": 1, "top_n": 1, "new_user_ratings": 3, "seed": 1}
    result = evaluate(train, test, B, new_user_pick="onboarding", **kw)
    assert result.new_user_pick == "onboarding"
    assert result.n_users == 10
    assert result.cf.precision_at_k == 1.0  # dropped train ratings are not recommended
    assert evaluate(train, test, B, new_user_pick="onboarding", **kw) == result


def test_random_pick_is_the_default():
    train, test = cold_data()
    kw = {"min_overlap": 1, "top_n": 3, "new_user_ratings": 3, "seed": 4}
    assert evaluate(train, test, B, new_user_pick="random", **kw) == evaluate(train, test, B, **kw)
    assert evaluate(train, test, B, **kw).new_user_pick == "random"


def test_new_user_pick_validation():
    train, test = cold_data()
    with pytest.raises(ValueError):
        evaluate(train, test, B, new_user_pick="onboarding")
    with pytest.raises(ValueError):
        evaluate(train, test, B, new_user_ratings=3, new_user_pick="bogus")


def test_new_user_seen_kept_excludes_only_the_kept_ratings(monkeypatch):
    from cinemate.evaluation import runner

    train, test = cold_data()
    real = runner.popular_by_likes
    calls: list[tuple[int, int]] = []

    def spy(matrix, exclude, n=10):
        exclude = set(exclude)
        out = real(matrix, exclude, n=n)
        calls.append((len(exclude), len(out)))
        return out

    monkeypatch.setattr(runner, "popular_by_likes", spy)
    kw = {"min_overlap": 1, "top_n": 12, "new_user_ratings": 3, "seed": 1}
    evaluate(train, test, B, **kw)
    assert {c[0] for c in calls} == {5} and {c[1] for c in calls} == {7}
    calls.clear()
    result = evaluate(train, test, B, new_user_seen="kept", **kw)
    # 3 kept ratings are excluded; the 2 dropped ones may be recommended (9 of 12 movies left)
    assert {c[0] for c in calls} == {3} and {c[1] for c in calls} == {9}
    assert result.new_user_seen == "kept"
    # a dropped train rating is not relevant: each user has exactly one relevant (test) movie
    assert result.baselines["popular_likes"].precision_at_k <= 1 / 12
    assert evaluate(train, test, B, new_user_seen="kept", **kw) == result


def test_new_user_seen_all_is_the_default():
    train, test = cold_data()
    kw = {"min_overlap": 1, "top_n": 3, "new_user_ratings": 3, "seed": 4}
    default = evaluate(train, test, B, **kw)
    assert evaluate(train, test, B, new_user_seen="all", **kw) == default
    assert default.new_user_seen == "all"


def test_new_user_seen_validation():
    train, test = cold_data()
    with pytest.raises(ValueError):
        evaluate(train, test, B, new_user_seen="kept")
    with pytest.raises(ValueError):
        evaluate(train, test, B, new_user_ratings=3, new_user_seen="bogus")


def test_new_users_line_with_seen():
    from cinemate.evaluation.runner import new_users_line

    assert new_users_line(5, "random") == "new users: 5 ratings each"
    assert new_users_line(5, "onboarding") == "new users: 5 ratings each (pick: onboarding)"
    assert (
        new_users_line(5, "onboarding", "kept")
        == "new users: 5 ratings each (pick: onboarding, seen: kept)"
    )
    assert (
        new_users_line(5, "random", "kept")
        == "new users: 5 ratings each (pick: random, seen: kept)"
    )


def test_evaluate_significance_validated_and_passed_through():
    with pytest.raises(ValueError, match="significance"):
        run(likes(1, 6, 7), significance=-1)
    assert run(likes(1, 6, 7), significance=0) == run(likes(1, 6, 7))


def test_evaluate_hybrid_rows_follow_blend_full_at():
    train, test = cold_data()
    kw = {"min_overlap": 1, "top_n": 3, "new_user_ratings": 3, "seed": 4}
    result = evaluate(train, test, B, blend_full_at=[3, 10.5], **kw)
    assert "hybrid(T=3)" in result.baselines
    assert "hybrid(T=10.5)" in result.baselines
    default = evaluate(train, test, B, **kw)
    assert not any(name.startswith("hybrid") for name in default.baselines)
    assert result.cf == default.cf


def test_evaluate_blend_full_at_must_be_positive():
    train, test = cold_data()
    with pytest.raises(ValueError, match="blend_full_at"):
        evaluate(train, test, B, blend_full_at=[0])


def test_evaluate_item_based_params_change_row():
    loose = run(likes(1, 6, 7), item_min_overlap=1).baselines["item_based"]
    strict = run(likes(1, 6, 7), item_min_overlap=100).baselines["item_based"]
    assert strict.coverage == 0.0
    assert loose.coverage > 0.0


def _spy_matrix(monkeypatch):
    from cinemate.evaluation import runner

    captured = {}
    real_build = runner.build_matrix

    def spy(ratings, binarizer):
        captured["train"] = list(ratings)
        return real_build(captured["train"], binarizer)

    monkeypatch.setattr(runner, "build_matrix", spy)
    return captured


def test_user_fraction_thins_established_users_only(monkeypatch):
    train, test = cold_data()
    captured = _spy_matrix(monkeypatch)
    kw = {"min_overlap": 1, "top_n": 3, "new_user_ratings": 3, "seed": 4}
    full = evaluate(train, test, B, **kw)
    full_users = {r.user_id for r in captured["train"]}
    half = evaluate(train, test, B, user_fraction=0.5, **kw)
    half_users = {r.user_id for r in captured["train"]}
    assert full.established_users is None
    assert half.established_users == (5, 10)
    assert half.user_fraction == 0.5
    assert len(full_users) == 20
    assert len(half_users) == 15  # 10 new + half of the 10 established
    assert half.n_users == full.n_users == 10


def test_user_fraction_keeps_the_same_new_users_for_any_fraction(monkeypatch):
    train, test = cold_data()
    captured = _spy_matrix(monkeypatch)
    kw = {"min_overlap": 1, "top_n": 3, "new_user_ratings": 3, "seed": 2}
    new_sets = []
    for fraction in (1.0, 0.5, 0.1):
        evaluate(train, test, B, user_fraction=fraction, **kw)
        counts = {}
        for r in captured["train"]:
            counts[r.user_id] = counts.get(r.user_id, 0) + 1
        new_sets.append({u for u, c in counts.items() if c == 3})
    assert new_sets[0] == new_sets[1] == new_sets[2]
    assert len(new_sets[0]) == 10


def test_user_fraction_keeps_at_least_one_established_user():
    train, test = cold_data()
    result = evaluate(
        train, test, B, min_overlap=1, new_user_ratings=3, seed=1, user_fraction=0.001
    )
    assert result.established_users == (1, 10)


def test_user_fraction_one_matches_default_and_is_deterministic():
    train, test = cold_data()
    kw = {"min_overlap": 1, "top_n": 3, "new_user_ratings": 3, "seed": 4}
    assert evaluate(train, test, B, user_fraction=1.0, **kw) == evaluate(train, test, B, **kw)
    first = evaluate(train, test, B, user_fraction=0.3, **kw)
    assert evaluate(train, test, B, user_fraction=0.3, **kw) == first


@pytest.mark.parametrize("fraction", [0, -0.5, 1.5])
def test_user_fraction_out_of_range(fraction):
    train, test = cold_data()
    with pytest.raises(ValueError, match="user_fraction"):
        evaluate(train, test, B, new_user_ratings=3, user_fraction=fraction)


def test_user_fraction_requires_new_user_ratings():
    train, test = cold_data()
    with pytest.raises(ValueError, match="requires new_user_ratings"):
        evaluate(train, test, B, user_fraction=0.5)


def test_test_dislike_in_top_counts_in_dislike_at_k_and_like_share():
    result = run(likes(1, 6) + [Rating(1, 7, 1.0)])
    assert result.n_users == 1
    assert result.cf.dislike_at_k == 0.5  # movie 7 is in the top-2 and disliked in test
    assert result.cf.like_share_judged == 0.5
    assert result.cf.judged_users == 1


def test_unrated_in_test_movie_is_not_judged():
    result = run(likes(1, 6))  # movie 7 is recommended too but has no test rating
    assert result.cf.dislike_at_k == 0.0
    assert result.cf.like_share_judged == 1.0
    assert result.cf.judged_users == 1


def test_user_without_judged_recommendations_is_left_out_of_like_share():
    # User 1 is judged (like 6, dislike 7: share 0.5); user 2's only test like (8) is not in
    # their top-2, so user 2 counts in dislike@k but not in the like share average.
    result = run(likes(1, 6) + [Rating(1, 7, 1.0)] + likes(2, 8))
    assert result.n_users == 2
    assert result.cf.judged_users == 1
    assert result.cf.like_share_judged == 0.5
    assert result.cf.dislike_at_k == 0.25


def test_no_judged_users_gives_zero_like_share():
    result = run(likes(1, 8))
    assert result.cf.judged_users == 0
    assert result.cf.like_share_judged == 0.0


def test_cf_taste_baseline_needs_features_and_matches_cf_without_weight():
    assert "cf+taste" not in run(likes(1, 6, 7)).baselines
    features = {m: MovieFeatures(genres=(14 if m % 2 else 18,)) for m in range(1, 11)}
    off = run(likes(1, 6, 7), features=features, settings=RecommenderSettings(taste_weight=0))
    assert off.baselines["cf+taste"].precision_at_k == off.cf.precision_at_k
    on = run(likes(1, 6, 7), features=features)
    assert set(on.baselines["cf+taste"].__dict__) == set(on.cf.__dict__)


def test_cf_taste_moves_liked_genre_up():
    train = likes(1, 1, 2, 3, 4) + likes(2, 1, 2, 3, 4, 5, 6) + likes(3, 1, 2, 3, 4, 5)
    # movie 5 (drama) is liked by one more neighbour than movie 6 (fantasy)
    features = {m: MovieFeatures(genres=(14,)) for m in (1, 2, 3, 4, 6)}
    features[5] = MovieFeatures(genres=(18,))
    settings = RecommenderSettings(taste_weight=3.0)
    kw = dict(k=5, lam=0.0, min_overlap=1, top_n=1, pop_penalty=0.0)
    cf = evaluate(train, likes(1, 6), B, features=features, settings=settings, **kw)
    assert cf.cf.precision_at_k == 0.0  # plain CF puts the drama first
    assert cf.baselines["cf+taste"].precision_at_k == 1.0


def test_cf_taste_rule_moves_a_disliked_genre_down():
    train = (
        likes(1, 1, 2, 3)
        + [Rating(1, m, 1.0) for m in (4, 5, 6)]  # user 1 dislikes three dramas, likes no drama
        + likes(2, 1, 2, 3, 7, 8)
        + likes(3, 1, 2, 3, 7)  # drama 7 has one more fan than fantasy 8
    )
    features = {m: MovieFeatures(genres=(14,)) for m in (1, 2, 3, 8)}
    features.update({m: MovieFeatures(genres=(18,)) for m in (4, 5, 6, 7)})
    settings = RecommenderSettings(taste_weight=0, hide_dislikes_genre=3, dislike_item_weight=0)
    kw = dict(k=5, lam=0.0, min_overlap=1, top_n=1, pop_penalty=0.0, settings=settings)
    plain = evaluate(train, likes(1, 8), B, **kw)
    assert "cf+taste+rule" not in plain.baselines
    result = evaluate(train, likes(1, 8), B, features=features, **kw)
    assert result.cf.precision_at_k == 0.0  # plain CF puts the drama first
    assert result.baselines["cf+taste"].precision_at_k == 0.0
    assert result.baselines["cf+taste+rule"].precision_at_k == 1.0


def test_cf_taste_rule_penalty_applies_from_the_ratings_threshold():
    # user 1 dislikes movie 4; movie 5 is liked together with 4 (users 6, 7), movie 6 is not
    train = (
        likes(1, 1, 2, 3)
        + [Rating(1, 4, 1.0)]
        + likes(2, 1, 2, 3, 5)
        + likes(3, 1, 2, 3, 5)
        + likes(4, 1, 2, 3, 6)
        + likes(5, 1, 2, 3, 6)
        + likes(6, 4, 5)
        + likes(7, 4, 5)
    )
    features = {m: MovieFeatures(genres=(14,)) for m in range(1, 8)}

    def top(settings, liked):
        result = evaluate(
            train, likes(1, liked), B, features=features, settings=settings, k=10, lam=0.0,
            min_overlap=1, top_n=1, pop_penalty=0.0,
        )  # fmt: skip
        return result.cf.precision_at_k, result.baselines["cf+taste+rule"].precision_at_k

    base = dict(taste_weight=0, dislike_item_min_ratings=4)
    off = RecommenderSettings(dislike_item_weight=0, **base)
    on = RecommenderSettings(dislike_item_weight=0.5, **base)
    too_few_ratings = RecommenderSettings(dislike_item_weight=0.5, taste_weight=0)
    assert top(off, 5) == (1.0, 1.0)  # plain CF and no penalty: movie 5 first
    assert top(on, 5) == (1.0, 0.0)  # similar to the disliked movie: pushed below movie 6
    assert top(on, 6) == (0.0, 1.0)
    assert top(too_few_ratings, 5) == (1.0, 1.0)  # fewer than 50 ratings: no penalty
