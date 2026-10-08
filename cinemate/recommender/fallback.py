"""Fallback strategy: popular, well-liked movies, shuffled within the top of the list."""

import random

import numpy as np
from scipy.sparse import csr_matrix

DEFAULT_MIN_RATINGS = 5
DEFAULT_POOL_FACTOR = 3


def popular(
    matrix: csr_matrix,
    user_index: int,
    n: int = 20,
    min_ratings: int = DEFAULT_MIN_RATINGS,
    pool_factor: int = DEFAULT_POOL_FACTOR,
    rng: random.Random | None = None,
) -> list[tuple[int, float]]:
    """Pick up to ``n`` popular movies for ``user_index``.

    A movie's score is its share of likes among all its ratings. Only movies with at least
    ``min_ratings`` ratings are considered, and movies the user already rated are excluded.
    The candidates are ranked by score (ties: more ratings first, then movie index), the top
    ``pool_factor * n`` form the pool, and ``n`` movies are drawn from it at random so that
    the output varies between users and visits. Pass a seeded ``rng`` for determinism.

    Returns ``(movie_index, like_share)`` pairs sorted by score descending (ties by movie
    index ascending). Returns an empty list if ``n <= 0``, ``pool_factor <= 0`` or nothing
    qualifies.
    """
    if n <= 0:
        return []
    rng = rng or random.Random()

    values = matrix.astype(np.float64)
    values.eliminate_zeros()
    totals = np.asarray(values.getnnz(axis=0)).ravel()
    likes = np.asarray((values > 0).sum(axis=0)).ravel()

    rated = values[user_index].indices
    candidates = np.flatnonzero(totals >= min_ratings)
    candidates = candidates[~np.isin(candidates, rated)]
    shares = likes[candidates] / totals[candidates]

    order = sorted(range(len(candidates)), key=lambda j: (-shares[j], -totals[candidates[j]]))
    pool = order[: pool_factor * n]
    chosen = rng.sample(pool, min(n, len(pool)))
    chosen.sort(key=lambda j: (-shares[j], candidates[j]))
    return [(int(candidates[j]), float(shares[j])) for j in chosen]
