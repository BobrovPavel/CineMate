"""User similarity: cosine closeness of +1 / -1 rows and top-K neighbour search."""

import numpy as np
from scipy.sparse import csr_matrix


def find_neighbors(
    matrix: csr_matrix, user_index: int, k: int = 40, min_overlap: int = 5
) -> list[tuple[int, float]]:
    """Find the ``k`` users most similar to ``user_index``.

    Similarity is the cosine between rows of ``matrix`` (entries ``+1`` / ``-1`` / ``0``).
    If two users have fewer than ``min_overlap`` co-rated movies, their similarity is 0.
    Only the target user's row is multiplied against the matrix; the full user x user
    matrix is never built.

    Returns ``(row_index, similarity)`` pairs with strictly positive similarity, sorted by
    similarity descending (ties by row index ascending), at most ``k`` long. The user
    itself is excluded.
    """
    if k <= 0:
        return []

    values = matrix.astype(np.float64)
    values.eliminate_zeros()
    target = values[user_index]

    dots = np.asarray((values @ target.T).todense()).ravel()
    row_norms = np.sqrt(np.asarray(values.multiply(values).sum(axis=1)).ravel())
    target_norm = row_norms[user_index]
    if target_norm == 0:
        return []

    target_mask = target.copy()
    target_mask.data[:] = 1.0
    mask = values.copy()
    mask.data[:] = 1.0
    overlaps = np.asarray((mask @ target_mask.T).todense()).ravel()

    denominators = row_norms * target_norm
    similarities = np.zeros_like(dots)
    valid = (denominators > 0) & (overlaps >= min_overlap)
    similarities[valid] = dots[valid] / denominators[valid]
    similarities[user_index] = 0.0

    candidates = np.flatnonzero(similarities > 0)
    ordered = sorted(candidates.tolist(), key=lambda i: (-similarities[i], i))
    return [(i, float(similarities[i])) for i in ordered[:k]]
