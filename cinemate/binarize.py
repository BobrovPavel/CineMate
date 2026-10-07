"""Rating binarization: map source-specific scores to +1 / -1 (or drop them)."""

from typing import Protocol


class Binarizer(Protocol):
    """Strategy that converts a raw rating into a like/dislike signal."""

    def binarize(self, score: float) -> int | None:
        """Return ``+1`` (like), ``-1`` (dislike) or ``None`` (discard the rating)."""
        ...


class MovieLensBinarizer:
    """Binarizer for MovieLens scores (0.5-5.0).

    Scores ``>= like_threshold`` become ``+1``, scores ``<= dislike_threshold``
    become ``-1``, everything in between is discarded.
    """

    def __init__(self, like_threshold: float = 3.5, dislike_threshold: float = 2.5) -> None:
        self.like_threshold = like_threshold
        self.dislike_threshold = dislike_threshold

    def binarize(self, score: float) -> int | None:
        """Return ``+1``, ``-1`` or ``None`` for the given MovieLens score."""
        if score >= self.like_threshold:
            return 1
        if score <= self.dislike_threshold:
            return -1
        return None
