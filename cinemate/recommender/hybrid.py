"""Hybrid recommender: a blend of popularity and CF weighted by the user's rating count."""

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix

from cinemate.recommender.scoring import candidate_stats
from cinemate.recommender.similarity import find_neighbors


@dataclass(frozen=True)
class HybridResult:
    """Hybrid items, the CF weight ``beta`` and whether the user had neighbours."""

    items: list[tuple[int, float]]
    beta: float
    has_neighbors: bool


def recommend_hybrid_detailed(
    matrix: csr_matrix,
    user_index: int,
    n: int = 20,
    k: int = 150,
    min_overlap: int = 1,
    lam: float = 40.0,
    blend_full_at: float = 30.0,
    significance: int = 0,
) -> HybridResult:
    """Like ``recommend_hybrid`` but also reports ``beta`` and whether neighbours were found."""
    if not blend_full_at > 0:
        raise ValueError("blend_full_at must be > 0")
    values = matrix.astype(np.float64)
    values.eliminate_zeros()
    row = values[user_index]
    beta = min(1.0, row.nnz / blend_full_at)
    neighbors = find_neighbors(
        matrix, user_index, k=k, min_overlap=min_overlap, significance=significance
    )
    if n <= 0:
        return HybridResult([], beta, bool(neighbors))

    likes = np.asarray((values > 0).sum(axis=0)).ravel()
    max_likes = likes.max() if likes.size else 0
    pop = likes / max_likes if max_likes > 0 else np.zeros(likes.shape)

    cf = np.zeros(values.shape[1])
    if neighbors:
        stats = candidate_stats(matrix, user_index, neighbors)
        raw = np.maximum(0.0, stats.norm) * stats.c / (stats.c + lam)
        peak = raw.max() if raw.size else 0.0
        if peak > 0:
            cf[stats.candidates] = raw / peak

    # Without neighbours there is nothing to blend: order by likes whatever beta is.
    scores = (1 - beta) * pop + beta * cf if neighbors else pop
    candidates = np.setdiff1d(np.arange(values.shape[1]), row.indices)
    order = sorted(candidates.tolist(), key=lambda m: (-scores[m], m))
    items = [(int(m), float(scores[m])) for m in order[:n]]
    return HybridResult(items, beta, bool(neighbors))


def recommend_hybrid(
    matrix: csr_matrix,
    user_index: int,
    n: int = 20,
    k: int = 150,
    min_overlap: int = 1,
    lam: float = 40.0,
    blend_full_at: float = 30.0,
    significance: int = 0,
) -> list[tuple[int, float]]:
    """Recommend up to ``n`` movies, smoothly moving from popularity to CF.

    With ``n_inf`` the user's non-zero ratings and ``beta = min(1, n_inf / blend_full_at)``::

        pop(m)       = likes(m) / max_likes                  (0 if nobody liked anything)
        cf(m)        = max(0, norm(m)) * c / (c + lam)       (0 if no neighbour rated m)
        cf_scaled(m) = cf(m) / max cf                        (0 everywhere if max is 0)
        score(m)     = (1 - beta) * pop(m) + beta * cf_scaled(m)

    ``norm`` and ``c`` are as in ``recommend`` (there is no popularity penalty here, ``pop``
    already accounts for it). Candidates are all movies the user has not rated. Without
    neighbours the order is by likes (``pop``) whatever ``beta`` is. Returns
    ``(movie_index, score)`` pairs by score descending (ties by movie index ascending).
    Raises ``ValueError`` if ``blend_full_at <= 0``.
    """
    return recommend_hybrid_detailed(
        matrix, user_index, n, k, min_overlap, lam, blend_full_at, significance
    ).items
