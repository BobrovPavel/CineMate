"""Building the sparse user x movie matrix of +1 / -1 ratings."""

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix

from cinemate.binarize import Binarizer
from cinemate.movielens import Rating


@dataclass(frozen=True)
class RatingsMatrix:
    """Sparse ratings matrix with id lookup tables.

    Position in ``user_ids`` / ``movie_ids`` is the row / column index in ``matrix``.
    """

    matrix: csr_matrix
    user_ids: list[int]
    movie_ids: list[int]


def build_matrix(ratings: Iterable[Rating], binarizer: Binarizer) -> RatingsMatrix:
    """Build a ``users x movies`` matrix with ``+1`` (like) and ``-1`` (dislike) entries.

    Ratings the binarizer discards (``None``) are skipped entirely and neither create
    rows/columns nor override earlier ratings. If a (user, movie) pair occurs several
    times, the last kept rating wins. Users and movies with no kept rating are omitted.
    Ids are sorted ascending to make indices deterministic.
    """
    values: dict[tuple[int, int], int] = {}
    for rating in ratings:
        value = binarizer.binarize(rating.score)
        if value is not None:
            values[(rating.user_id, rating.movie_id)] = value

    return matrix_from_values((user, movie, value) for (user, movie), value in values.items())


def matrix_from_values(triples: Iterable[tuple[int, int, int]]) -> RatingsMatrix:
    """Build a ``users x movies`` matrix from already binarized ``(user, movie, value)`` triples.

    Values must be ``+1`` or ``-1``. If a (user, movie) pair occurs several times, the last
    one wins. Ids are sorted ascending to make indices deterministic.
    """
    values = {(user, movie): value for user, movie, value in triples}

    user_ids = sorted({user for user, _ in values})
    movie_ids = sorted({movie for _, movie in values})
    user_index = {user: i for i, user in enumerate(user_ids)}
    movie_index = {movie: i for i, movie in enumerate(movie_ids)}

    rows = [user_index[user] for user, _ in values]
    cols = [movie_index[movie] for _, movie in values]
    data = np.fromiter(values.values(), dtype=np.int8, count=len(values))
    matrix = csr_matrix((data, (rows, cols)), shape=(len(user_ids), len(movie_ids)))
    return RatingsMatrix(matrix=matrix, user_ids=user_ids, movie_ids=movie_ids)
