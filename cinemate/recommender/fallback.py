"""Fallback strategy: movies with the most likes, shuffled within the top of the list."""

import random

import numpy as np
from scipy.sparse import csr_matrix

DEFAULT_MIN_RATINGS = 1
DEFAULT_POOL_FACTOR = 2


def popular(
    matrix: csr_matrix,
    user_index: int,
    n: int = 20,
    min_ratings: int = DEFAULT_MIN_RATINGS,
    pool_factor: int = DEFAULT_POOL_FACTOR,
    rng: random.Random | None = None,
) -> list[tuple[int, float]]:
    """Pick up to ``n`` popular movies for ``user_index``, ranked by number of likes.

    Only movies with at least ``min_ratings`` ratings are considered, and movies the user
    already rated are excluded. Candidates are ranked by the number of likes (``+1``)
    descending (ties: higher share of likes, then lower movie index), the first
    ``pool_factor * n`` form the pool, and ``n`` movies are drawn from it at random so that
    the output varies between users and visits. ``pool_factor=1`` gives the exact top. Pass a
    seeded ``rng`` for determinism.

    Returns ``(movie_index, score)`` pairs sorted by likes descending (ties by movie index
    ascending), where the score is the movie's likes divided by the largest like count among
    all movies (in ``[0, 1]``; ``0.0`` if nobody liked anything). Returns an empty list if
    ``n <= 0``, ``pool_factor <= 0`` or nothing qualifies.
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
    max_likes = int(likes.max()) if likes.size else 0

    order = sorted(
        range(len(candidates)), key=lambda j: (-likes[candidates[j]], -shares[j], candidates[j])
    )
    pool = order[: pool_factor * n]
    chosen = rng.sample(pool, min(n, len(pool)))
    chosen.sort(key=lambda j: (-likes[candidates[j]], candidates[j]))
    return [
        (int(candidates[j]), float(likes[candidates[j]]) / max_likes if max_likes else 0.0)
        for j in chosen
    ]
