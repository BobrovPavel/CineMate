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
