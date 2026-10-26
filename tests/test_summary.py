import pytest

from cinemate.binarize import RelativeMeanBinarizer
from cinemate.evaluation.summary import DatasetSummary, describe_ratings, format_summary
from cinemate.movielens import Rating


def test_describe_ratings_numbers():
    # user 1 mean 6: scores 9 (+1), 3 (-1), 6 (discarded); user 2 is unknown (discarded)
    ratings = [
        Rating(1, 1, 9.0),
        Rating(1, 2, 3.0),
        Rating(1, 3, 6.0),
        Rating(2, 1, 5.0),
    ]
    summary = describe_ratings(ratings, RelativeMeanBinarizer({1: 6.0}))
    assert summary.n_users == 2
    assert summary.n_movies == 3
    assert summary.n_ratings == 4
    assert summary.mean_per_user == 2.0
    assert summary.median_per_user == 2.0
    assert summary.density == pytest.approx(4 / 6)
    assert summary.like_share == 0.25
    assert summary.dislike_share == 0.25
    assert summary.discarded_share == 0.5


def test_describe_empty():
    assert describe_ratings([], RelativeMeanBinarizer({})).n_ratings == 0


def test_format_summary():
    summary = DatasetSummary(1500, 42000, 900000, 600.0, 410.0, 0.0143, 0.382, 0.215, 0.403)
    assert format_summary(summary) == (
        "dataset: 1500 users, 42000 movies, 900000 ratings (median 410 per user, "
        "density 1.43%); binarized: +1 38.2%, -1 21.5%, discarded 40.3%"
    )
