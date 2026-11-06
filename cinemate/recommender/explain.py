"""Data for explaining a recommendation: who liked the movie and what it is tied to."""

from collections import Counter
from dataclasses import dataclass

from scipy.sparse import csr_matrix

MAX_BECAUSE_OF = 3
TWIN_MIN_COMMON = 5
TWIN_MIN_SHARE = 0.6
TWIN_MIN_MASS_SHARE = 0.5


@dataclass(frozen=True)
class Twin:
    """A very similar neighbour behind a recommendation: ``common`` likes shared with the
    user out of the user's ``of`` likes. Only numbers, no user identifiers."""

    common: int
    of: int


@dataclass(frozen=True)
class Explanation:
    """Why a movie was recommended.

    ``liked_by`` is how many of the given neighbours liked the movie (``+1``).
    ``because_of`` holds up to 3 movie indices the user liked and that were also liked by
    the neighbours who liked the recommended movie, most frequent first (ties by index
    ascending). It is empty if there are no such movies. Only indices, no texts.
    ``twin`` is set if the movie is mostly owed to one very similar neighbour (see ``explain``).
    """

    liked_by: int
    because_of: list[int]
    twin: Twin | None = None


def _liked_columns(matrix: csr_matrix, row: int) -> set[int]:
    """Column indices with a ``+1`` entry in ``row``, read straight from the CSR arrays."""
    start, end = matrix.indptr[row], matrix.indptr[row + 1]
    return set(matrix.indices[start:end][matrix.data[start:end] > 0].tolist())


def explain(
    matrix: csr_matrix,
    user_index: int,
    movie_index: int,
    neighbors: list[tuple[int, float]],
    sim_power: float = 1.0,
    liked_cache: dict[int, set[int]] | None = None,
) -> Explanation:
    """Explain recommending ``movie_index`` to ``user_index`` via ``neighbors``.

    ``neighbors`` is the output of ``find_neighbors`` (``(row_index, similarity)`` pairs).
    Only ``+1`` entries count as likes; neighbours' dislikes are ignored. The recommended
    movie itself never appears in ``because_of``.

    ``twin`` is the most similar neighbour who liked the movie if (a) it shares at least 5 likes
    with the user and at least 60 % of the user's likes, and (b) its weight ``sim ** sim_power``
    is at least half of the total weight of the neighbours who liked the movie, i.e. the
    recommendation is mainly its doing.

    ``liked_cache`` (row index -> liked columns) may be shared between calls for the same
    ``matrix`` to avoid reading the same rows again when many movies are explained; it is
    filled in by this function and its sets are never modified.
    """
    if liked_cache is None:
        liked_cache = {}

    def likes_of(row: int) -> set[int]:
        found = liked_cache.get(row)
        if found is None:
            found = liked_cache[row] = _liked_columns(matrix, row)
        return found

    user_likes = set(likes_of(user_index))
    user_likes.discard(movie_index)

    liked_by = 0
    counts: Counter[int] = Counter()
    mass = 0.0
    best: tuple[float, int] | None = None  # (similarity, shared likes) of the closest liker
    for row_index, sim in neighbors:
        liked = likes_of(row_index)
        if movie_index not in liked:
            continue
        liked_by += 1
        shared = liked & user_likes
        counts.update(shared)
        mass += sim**sim_power
        if best is None or sim > best[0]:
            best = (sim, len(shared))

    twin = None
    of = len(user_likes)
    if best is not None and mass > 0:
        sim, common = best
        if (
            common >= TWIN_MIN_COMMON
            and of > 0
            and common / of >= TWIN_MIN_SHARE
            and sim**sim_power / mass >= TWIN_MIN_MASS_SHARE
        ):
            twin = Twin(common=common, of=of)

    ranked = sorted(counts, key=lambda j: (-counts[j], j))
    return Explanation(liked_by=liked_by, because_of=ranked[:MAX_BECAUSE_OF], twin=twin)
