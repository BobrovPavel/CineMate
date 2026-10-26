"""One-line description of a ratings dataset, printed above the evaluation tables."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from cinemate.binarize import Binarizer
from cinemate.movielens import Rating


@dataclass(frozen=True)
class DatasetSummary:
    n_users: int
    n_movies: int
    n_ratings: int
    mean_per_user: float
    median_per_user: float
    density: float
    like_share: float
    dislike_share: float
    discarded_share: float


def describe_ratings(ratings: Sequence[Rating], binarizer: Binarizer) -> DatasetSummary:
    """Count users, movies and ratings and the binarized shares of ``ratings``."""
    per_user = Counter(r.user_id for r in ratings)
    n_movies = len({r.movie_id for r in ratings})
    n_users = len(per_user)
    n_ratings = len(ratings)
    labels = Counter(binarizer.binarize(r.score, r.user_id) for r in ratings)

    def share(count: int) -> float:
        return count / n_ratings if n_ratings else 0.0

    return DatasetSummary(
        n_users=n_users,
        n_movies=n_movies,
        n_ratings=n_ratings,
        mean_per_user=n_ratings / n_users if n_users else 0.0,
        median_per_user=float(median(per_user.values())) if per_user else 0.0,
        density=n_ratings / (n_users * n_movies) if n_users and n_movies else 0.0,
        like_share=share(labels[1]),
        dislike_share=share(labels[-1]),
        discarded_share=share(labels[None]),
    )


def format_summary(summary: DatasetSummary) -> str:
    """Render ``summary`` as a single line."""
    return (
        f"dataset: {summary.n_users} users, {summary.n_movies} movies, "
        f"{summary.n_ratings} ratings (median {summary.median_per_user:g} per user, "
        f"density {summary.density:.2%}); "
        f"binarized: +1 {summary.like_share:.1%}, -1 {summary.dislike_share:.1%}, "
        f"discarded {summary.discarded_share:.1%}"
    )
