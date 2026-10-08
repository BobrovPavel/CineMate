import pytest

from cinemate.binarize import MovieLensBinarizer
from cinemate.evaluation.runner import evaluate, popular_baseline
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
    assert result.baseline.precision_at_k == 0.0
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
