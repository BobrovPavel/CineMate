"""Data for explaining a recommendation: who liked the movie and what it is tied to."""

from collections import Counter
from dataclasses import dataclass

from scipy.sparse import csr_matrix

MAX_BECAUSE_OF = 3


@dataclass(frozen=True)
class Explanation:
    """Why a movie was recommended.

    ``liked_by`` is how many of the given neighbours liked the movie (``+1``).
    ``because_of`` holds up to 3 movie indices the user liked and that were also liked by
    the neighbours who liked the recommended movie, most frequent first (ties by index
    ascending). It is empty if there are no such movies. Only indices, no texts.
    """

    liked_by: int
    because_of: list[int]


def _liked_columns(matrix: csr_matrix, row: int) -> set[int]:
    """Column indices with a ``+1`` entry in ``row``, read straight from the CSR arrays."""
    start, end = matrix.indptr[row], matrix.indptr[row + 1]
    return set(matrix.indices[start:end][matrix.data[start:end] > 0].tolist())


def explain(
    matrix: csr_matrix,
    user_index: int,
    movie_index: int,
    neighbors: list[tuple[int, float]],
) -> Explanation:
    """Explain recommending ``movie_index`` to ``user_index`` via ``neighbors``.

    ``neighbors`` is the output of ``find_neighbors`` (``(row_index, similarity)`` pairs).
    Only ``+1`` entries count as likes; neighbours' dislikes are ignored. The recommended
    movie itself never appears in ``because_of``.
    """
    user_likes = _liked_columns(matrix, user_index)
    user_likes.discard(movie_index)

    liked_by = 0
    counts: Counter[int] = Counter()
    for row_index, _ in neighbors:
        liked = _liked_columns(matrix, row_index)
        if movie_index not in liked:
            continue
        liked_by += 1
        counts.update(liked & user_likes)

    ranked = sorted(counts, key=lambda j: (-counts[j], j))
    return Explanation(liked_by=liked_by, because_of=ranked[:MAX_BECAUSE_OF])
