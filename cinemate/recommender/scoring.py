"""Neighbour-based movie scoring with shrinkage and a popularity penalty."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.sparse import csr_matrix

from cinemate.recommender.similarity import find_neighbors

Shrink = Literal["count", "mass"]
SHRINK_MODES = ("count", "mass")


@dataclass(frozen=True)
class CandidateStats:
    """Per-candidate statistics aligned with ``candidates`` (sorted movie indices).

    ``norm`` is ``sum(w * rating) / sum(w)`` over the neighbours who rated the movie with
    ``w = sim ** sim_power``, ``c`` their number, ``mass`` the sum ``S`` of ``w`` and ``likes``
    the number of ``+1`` ratings among all users.
    """

    candidates: np.ndarray
    norm: np.ndarray
    c: np.ndarray
    likes: np.ndarray
    mass: np.ndarray


def shrink_factor(
    stats: CandidateStats, lam: float, shrink: Shrink = "count", mass_lambda: float = 0.5
) -> np.ndarray:
    """Smoothing factor per candidate: ``c / (c + lam)`` (``count``) or ``S / (S + mass_lambda)``
    (``mass``, ``S`` is the similarity mass of the neighbours who rated the movie)."""
    if shrink == "mass":
        return stats.mass / (stats.mass + mass_lambda)
    return stats.c / (stats.c + lam)


def candidate_stats(
    matrix: csr_matrix,
    user_index: int,
    neighbors: list[tuple[int, float]],
    sim_power: float = 1.0,
) -> CandidateStats:
    """Statistics of the movies rated by at least one neighbour and not by the user.

    ``neighbors`` must be non-empty (as returned by ``find_neighbors``). Similarities are
    raised to ``sim_power`` (case amplification) in the numerator and the denominator.
    """
    values = matrix.astype(np.float64)
    values.eliminate_zeros()
    rows = [i for i, _ in neighbors]
    sims = np.array([s for _, s in neighbors]) ** sim_power
    block = values[rows]

    weighted = np.asarray(block.multiply(sims[:, None]).sum(axis=0)).ravel()
    abs_sims = np.asarray(block.astype(bool).multiply(np.abs(sims)[:, None]).sum(axis=0)).ravel()
    counts = np.asarray(block.getnnz(axis=0)).ravel()
    likes = np.asarray((values > 0).sum(axis=0)).ravel()

    rated = values[user_index].indices
    candidates = np.flatnonzero(counts > 0)
    candidates = candidates[~np.isin(candidates, rated)]
    return CandidateStats(
        candidates=candidates,
        norm=weighted[candidates] / abs_sims[candidates],
        c=counts[candidates],
        likes=likes[candidates],
        mass=abs_sims[candidates],
    )


def recommend(
    matrix: csr_matrix,
    user_index: int,
    n: int = 20,
    k: int = 40,
    min_overlap: int = 5,
    lam: float = 5.0,
    pop_penalty: float = 1.0,
    significance: int = 0,
    neighbors: list[tuple[int, float]] | None = None,
    sim_power: float = 1.0,
    shrink: Shrink = "count",
    mass_lambda: float = 0.5,
) -> list[tuple[int, float]]:
    """Recommend up to ``n`` movies for ``user_index``.

    For each candidate movie ``m`` rated by at least one neighbour (see ``find_neighbors``)::

        w     = sim ** sim_power
        norm  = sum(w * rating) / sum(w)           over neighbours who rated m
        score = norm * shrink / log(2 + likes(m)) ** pop_penalty

    where ``shrink`` is ``c / (c + lam)`` for ``shrink="count"`` (``c`` is the number of
    neighbours who rated ``m``) or ``S / (S + mass_lambda)`` for ``"mass"`` (``S = sum(w)``
    over those neighbours), and ``likes(m)`` is the number of ``+1`` ratings of ``m`` among
    all users. ``sim_power=1`` with ``"count"`` is the original formula. ``pop_penalty`` is
    the exponent of the popularity penalty: ``1.0`` is the formula above, ``0.0`` disables it.
    ``significance`` is passed to ``find_neighbors``; precomputed ``neighbors`` (its output) skip
    that call. Dislikes of neighbours lower the score. Movies the user has already rated are
    excluded.

    Returns ``(movie_index, score)`` pairs sorted by score descending (ties by movie index
    ascending). Returns an empty list if there are no neighbours or ``n <= 0``. Raises
    ``ValueError`` if ``pop_penalty`` is negative, ``sim_power`` is not positive,
    ``mass_lambda`` is negative or ``shrink`` is unknown.
    """
    if not pop_penalty >= 0:
        raise ValueError("pop_penalty must be >= 0")
    if not sim_power > 0:
        raise ValueError("sim_power must be > 0")
    if not mass_lambda >= 0:
        raise ValueError("mass_lambda must be >= 0")
    if shrink not in SHRINK_MODES:
        raise ValueError(f"shrink must be one of {', '.join(SHRINK_MODES)}")
    if n <= 0:
        return []
    if neighbors is None:
        neighbors = find_neighbors(
            matrix, user_index, k=k, min_overlap=min_overlap, significance=significance
        )
    if not neighbors:
        return []

    stats = candidate_stats(matrix, user_index, neighbors, sim_power)
    candidates = stats.candidates

    factor = shrink_factor(stats, lam, shrink, mass_lambda)
    scores = stats.norm * factor / np.log(2 + stats.likes) ** pop_penalty

    order = sorted(range(len(candidates)), key=lambda j: (-scores[j], candidates[j]))
    return [(int(candidates[j]), float(scores[j])) for j in order[:n]]
