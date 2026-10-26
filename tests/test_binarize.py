import pytest

from cinemate.binarize import Binarizer, MovieLensBinarizer, RelativeMeanBinarizer
from cinemate.movielens import Rating
from cinemate.recommender.matrix import build_matrix


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.5, -1),
        (2.5, -1),
        (3.0, None),
        (3.5, 1),
        (5.0, 1),
    ],
)
def test_default_thresholds(score: float, expected: int | None) -> None:
    assert MovieLensBinarizer().binarize(score) == expected


@pytest.mark.parametrize(
    ("score", "expected"),
    [(2.0, -1), (2.5, None), (3.5, None), (4.0, 1), (4.5, 1)],
)
def test_custom_thresholds(score: float, expected: int | None) -> None:
    assert MovieLensBinarizer(like_threshold=4.0, dislike_threshold=2.0).binarize(score) == expected


def test_satisfies_protocol() -> None:
    binarizer: Binarizer = MovieLensBinarizer()
    assert binarizer.binarize(4.0) == 1


def test_movielens_binarizer_ignores_user_id():
    assert MovieLensBinarizer().binarize(4.0, user_id=7) == 1
    assert MovieLensBinarizer().binarize(1.0, 7) == -1


def test_relative_mean_boundaries_are_inclusive():
    # mean 8.0, threshold 0.5: +0.5 -> like, -0.5 -> dislike
    binarizer = RelativeMeanBinarizer({1: 8.0})
    assert binarizer.binarize(8.5, 1) == 1
    assert binarizer.binarize(7.5, 1) == -1
    assert binarizer.binarize(8.25, 1) is None
    assert binarizer.binarize(7.75, 1) is None


def test_relative_mean_same_score_differs_by_user_scale():
    binarizer = RelativeMeanBinarizer({1: 8.8, 2: 5.9})
    assert binarizer.binarize(8, 1) == -1
    assert binarizer.binarize(8, 2) == 1


def test_relative_mean_unknown_user_is_discarded():
    assert RelativeMeanBinarizer({1: 8.0}).binarize(10, 2) is None


def test_relative_mean_requires_user_id():
    with pytest.raises(ValueError):
        RelativeMeanBinarizer({1: 8.0}).binarize(8)


@pytest.mark.parametrize("threshold", [0, -0.5])
def test_relative_mean_rejects_non_positive_threshold(threshold):
    with pytest.raises(ValueError):
        RelativeMeanBinarizer({}, threshold=threshold)


def test_fit_requires_min_ratings():
    few = [Rating(1, m, 8.0) for m in range(19)]
    enough = [Rating(2, m, 8.0) for m in range(20)]
    binarizer = RelativeMeanBinarizer.fit(few + enough)
    assert binarizer.user_means == {2: 8.0}
    assert binarizer.binarize(10, 1) is None
    assert binarizer.binarize(10, 2) == 1


def test_fit_custom_min_ratings_and_threshold():
    ratings = [Rating(1, 1, 4.0), Rating(1, 2, 6.0)]
    binarizer = RelativeMeanBinarizer.fit(ratings, min_ratings=2, threshold=1.0)
    assert binarizer.user_means == {1: 5.0}
    assert binarizer.binarize(6.0, 1) == 1
    assert binarizer.binarize(5.5, 1) is None


def test_build_matrix_with_relative_mean_binarizer():
    # user 1 is a generous rater (mean 9.0), user 2 a strict one (mean 5.5)
    ratings = [Rating(1, m, 9.0) for m in range(1, 19)]
    ratings += [Rating(1, 100, 10.0), Rating(1, 101, 8.0)]
    ratings += [Rating(2, m, 5.5) for m in range(1, 19)]
    ratings += [Rating(2, 100, 6.5), Rating(2, 101, 4.5), Rating(2, 102, 5.5)]
    ratings += [Rating(3, 100, 10.0)]  # too few ratings -> dropped
    binarizer = RelativeMeanBinarizer.fit(ratings)
    built = build_matrix(ratings, binarizer)
    assert built.user_ids == [1, 2]
    dense = built.matrix.toarray()
    movie = {m: i for i, m in enumerate(built.movie_ids)}
    assert dense[0, movie[100]] == 1 and dense[0, movie[101]] == -1
    assert dense[1, movie[100]] == 1 and dense[1, movie[101]] == -1
    assert 102 not in movie
