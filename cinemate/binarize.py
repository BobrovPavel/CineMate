"""Rating binarization: map source-specific scores to +1 / -1 (or drop them)."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Protocol

from cinemate.movielens import Rating


class Binarizer(Protocol):
    """Strategy that converts a raw rating into a like/dislike signal."""

    def binarize(self, score: float, user_id: int | None = None) -> int | None:
        """Return ``+1`` (like), ``-1`` (dislike) or ``None`` (discard the rating).

        ``user_id`` identifies the author of the score for per-user strategies.
        """
        ...


class MovieLensBinarizer:
    """Binarizer for MovieLens scores (0.5-5.0).

    Scores ``>= like_threshold`` become ``+1``, scores ``<= dislike_threshold``
    become ``-1``, everything in between is discarded.
    """

    def __init__(self, like_threshold: float = 3.5, dislike_threshold: float = 2.5) -> None:
        self.like_threshold = like_threshold
        self.dislike_threshold = dislike_threshold

    def binarize(self, score: float, user_id: int | None = None) -> int | None:
        """Return ``+1``, ``-1`` or ``None`` for the given MovieLens score (``user_id`` unused)."""
        if score >= self.like_threshold:
            return 1
        if score <= self.dislike_threshold:
            return -1
        return None


class RelativeMeanBinarizer:
    """Binarizer relative to each user's personal mean score (e.g. a 1-10 scale).

    A deviation ``score - mean`` of at least ``+threshold`` becomes ``+1``, at most
    ``-threshold`` becomes ``-1``, anything in between is discarded. Users missing from
    ``user_means`` (too few ratings) have all their ratings discarded.
    """

    def __init__(self, user_means: Mapping[int, float], threshold: float = 0.5) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self.user_means = user_means
        self.threshold = threshold

    @classmethod
    def fit(
        cls, ratings: Iterable[Rating], min_ratings: int = 20, threshold: float = 0.5
    ) -> "RelativeMeanBinarizer":
        """Compute means for users with at least ``min_ratings`` ratings."""
        scores: dict[int, list[float]] = defaultdict(list)
        for rating in ratings:
            scores[rating.user_id].append(rating.score)
        means = {user: sum(v) / len(v) for user, v in scores.items() if len(v) >= min_ratings}
        return cls(means, threshold)

    def binarize(self, score: float, user_id: int | None = None) -> int | None:
        """Return ``+1``, ``-1`` or ``None`` relative to the user's mean."""
        if user_id is None:
            raise ValueError("RelativeMeanBinarizer requires user_id")
        mean = self.user_means.get(user_id)
        if mean is None:
            return None
        deviation = score - mean
        if deviation >= self.threshold:
            return 1
        if deviation <= -self.threshold:
            return -1
        return None
