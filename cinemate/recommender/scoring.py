"""Neighbour-based movie scoring with shrinkage and a popularity penalty."""

import numpy as np
from scipy.sparse import csr_matrix

from cinemate.recommender.similarity import find_neighbors


def recommend(
    matrix: csr_matrix,
    user_index: int,
    n: int = 20,
    k: int = 40,
    min_overlap: int = 5,
    lam: float = 5.0,
) -> list[tuple[int, float]]:
    """Recommend up to ``n`` movies for ``user_index``.

    For each candidate movie ``m`` rated by at least one neighbour (see ``find_neighbors``)::

        norm  = sum(sim * rating) / sum(|sim|)     over neighbours who rated m
        score = norm * c / (c + lam) / log(2 + likes(m))

    where ``c`` is the number of neighbours who rated ``m`` and ``likes(m)`` is the number of
    ``+1`` ratings of ``m`` among all users. Dislikes of neighbours lower the score. Movies
    the user has already rated are excluded.

    Returns ``(movie_index, score)`` pairs sorted by score descending (ties by movie index
    ascending). Returns an empty list if there are no neighbours or ``n <= 0``.
    """
    if n <= 0:
        return []
    neighbors = find_neighbors(matrix, user_index, k=k, min_overlap=min_overlap)
    if not neighbors:
        return []

    values = matrix.astype(np.float64)
    values.eliminate_zeros()
    rows = [i for i, _ in neighbors]
    sims = np.array([s for _, s in neighbors])
    block = values[rows]

    weighted = np.asarray(block.multiply(sims[:, None]).sum(axis=0)).ravel()
    abs_sims = np.asarray(block.astype(bool).multiply(np.abs(sims)[:, None]).sum(axis=0)).ravel()
    counts = np.asarray(block.getnnz(axis=0)).ravel()
    likes = np.asarray((values > 0).sum(axis=0)).ravel()

    rated = values[user_index].indices
    candidates = np.flatnonzero(counts > 0)
    candidates = candidates[~np.isin(candidates, rated)]

    norm = weighted[candidates] / abs_sims[candidates]
    c = counts[candidates]
    scores = norm * c / (c + lam) / np.log(2 + likes[candidates])

    order = sorted(range(len(candidates)), key=lambda j: (-scores[j], candidates[j]))
    return [(int(candidates[j]), float(scores[j])) for j in order[:n]]
