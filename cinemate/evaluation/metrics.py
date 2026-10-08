"""Pure quality metrics for recommendations and a per-user train/test split."""

import random
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence

from cinemate.movielens import Rating

MIN_RATINGS_FOR_TEST = 5


def split_ratings(
    ratings: Iterable[Rating], test_fraction: float = 0.2, seed: int = 0
) -> tuple[list[Rating], list[Rating]]:
    """Split ratings into ``(train, test)`` separately for each user.

    Users with fewer than 5 ratings get an empty test part. Every other user gets
    ``round(n * test_fraction)`` test ratings, at least 1 and at most ``n - 1``.
    The result is deterministic for a fixed ``seed`` and the same input order.
    """
    if not 0.0 <= test_fraction < 1.0:
        raise ValueError("test_fraction must be in [0, 1)")
    by_user: dict[int, list[Rating]] = defaultdict(list)
    for rating in ratings:
        by_user[rating.user_id].append(rating)

    rng = random.Random(seed)
    train: list[Rating] = []
    test: list[Rating] = []
    for user_id in sorted(by_user):
        items = by_user[user_id]
        if len(items) < MIN_RATINGS_FOR_TEST or test_fraction == 0.0:
            train.extend(items)
            continue
        n_test = min(len(items) - 1, max(1, round(len(items) * test_fraction)))
        test_idx = set(rng.sample(range(len(items)), n_test))
        for i, rating in enumerate(items):
            (test if i in test_idx else train).append(rating)
    return train, test


def _hits(recommended: Sequence[int], relevant: Collection[int], k: int) -> int:
    return len(set(recommended[:k]) & set(relevant))


def precision_at_k(recommended: Sequence[int], relevant: Collection[int], k: int) -> float:
    """Share of the top-``k`` recommendations that are relevant.

    The denominator is ``k`` (a short list is penalised). Returns ``0.0`` if ``k <= 0``.
    """
    if k <= 0:
        return 0.0
    return _hits(recommended, relevant, k) / k


def recall_at_k(recommended: Sequence[int], relevant: Collection[int], k: int) -> float:
    """Share of relevant items found in the top-``k``; ``0.0`` if ``relevant`` is empty."""
    relevant_set = set(relevant)
    if k <= 0 or not relevant_set:
        return 0.0
    return _hits(recommended, relevant_set, k) / len(relevant_set)


def coverage(all_recommended: Iterable[Iterable[int]], n_movies: int) -> float:
    """Fraction of the catalogue that appears in at least one recommendation list."""
    if n_movies <= 0:
        return 0.0
    seen = {movie for rec in all_recommended for movie in rec}
    return len(seen) / n_movies


def mean_popularity(recommended: Iterable[int], popularity: Mapping[int, float]) -> float:
    """Average popularity of recommended movies; unknown movies count as ``0``.

    Returns ``0.0`` for an empty list.
    """
    items = list(recommended)
    if not items:
        return 0.0
    return sum(popularity.get(m, 0.0) for m in items) / len(items)
