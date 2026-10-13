"""Item-based collaborative filtering: movies are scored by similarity to the user's rated ones."""

import numpy as np
from scipy.sparse import csr_matrix


def recommend_item_based(
    matrix: csr_matrix,
    user_index: int,
    n: int = 20,
    min_overlap: int = 3,
    lam: float = 5.0,
) -> list[tuple[int, float]]:
    """Top-``n`` unrated movies by similarity to the movies the user rated.

    ``matrix`` is users x movies with ``+1/-1/0``. The cosine similarity of movies ``i`` and ``j``
    is taken over their columns and is ``0`` when fewer than ``min_overlap`` users rated both.
    For a candidate ``m`` and the user's rated movies ``J``,
    ``norm(m) = sum_j sim(m, j) * r_uj / sum_j |sim(m, j)|`` over ``j`` with ``sim != 0``, and
    ``score(m) = norm(m) * c / (c + lam)`` where ``c`` is the number of such ``j``. Candidates
    without a non-zero similarity are skipped. The movie x movie matrix is never built: for each
    ``j`` only its own column is multiplied with the transposed matrix.

    Ties: lower movie index first. Returns ``[]`` for ``n <= 0``, a user without ratings or
    without candidates.
    """
    if n <= 0:
        return []
    values = matrix.astype(np.float64).tocsr()
    values.eliminate_zeros()
    row = values[user_index]
    if row.nnz == 0:
        return []
    by_movie = values.T.tocsr()
    counts = np.diff(by_movie.indptr).astype(np.float64)
    overlap_source = abs(by_movie)

    n_movies = values.shape[1]
    weighted = np.zeros(n_movies)
    weights = np.zeros(n_movies)
    support = np.zeros(n_movies)
    for j, r_uj in zip(row.indices, row.data, strict=True):
        column = by_movie[j].T
        dots = (by_movie @ column).tocoo()
        overlaps = (overlap_source @ abs(column)).tocoo()
        overlap = np.zeros(n_movies)
        overlap[overlaps.row] = overlaps.data
        for m, dot in zip(dots.row, dots.data, strict=True):
            if overlap[m] < min_overlap:
                continue
            sim = dot / np.sqrt(counts[m] * counts[j])
            if sim == 0:
                continue
            weighted[m] += sim * r_uj
            weights[m] += abs(sim)
            support[m] += 1

    rated = set(row.indices.tolist())
    candidates = [m for m in np.flatnonzero(support) if int(m) not in rated]
    scores = {
        int(m): float(weighted[m] / weights[m] * support[m] / (support[m] + lam))
        for m in candidates
    }
    order = sorted(scores, key=lambda m: (-scores[m], m))
    return [(m, scores[m]) for m in order[:n]]
