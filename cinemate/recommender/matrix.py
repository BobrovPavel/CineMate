"""Build the sparse user x movie matrix of +1 / -1 ratings."""

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix

from cinemate.binarize import Binarizer
from cinemate.movielens import Rating


@dataclass(frozen=True)
class RatingsMatrix:
    """Sparse ratings matrix with the id lists that map rows/columns back to ids.

    ``matrix[i, j]`` is the rating of ``user_ids[i]`` for ``movie_ids[j]``; absent entries mean
    "not rated" (and are not stored).
    """

    matrix: csr_matrix
    user_ids: list[int]
    movie_ids: list[int]


def build_matrix(ratings: Iterable[Rating], binarizer: Binarizer) -> RatingsMatrix:
    """Binarize ``ratings`` and assemble them into a :class:`RatingsMatrix`.

    Ratings the binarizer discards (``None``) are skipped. If a (user, movie) pair occurs more
    than once, the last kept rating wins. Users and movies with no kept rating are omitted.
    Users and movies are indexed in ascending id order.
    """
    values: dict[tuple[int, int], int] = {}
    for rating in ratings:
        value = binarizer.binarize(rating.score)
        if value is not None:
            values[(rating.user_id, rating.movie_id)] = value

    user_ids = sorted({user for user, _ in values})
    movie_ids = sorted({movie for _, movie in values})
    user_index = {user: i for i, user in enumerate(user_ids)}
    movie_index = {movie: j for j, movie in enumerate(movie_ids)}

    rows = [user_index[user] for user, _ in values]
    cols = [movie_index[movie] for _, movie in values]
    data = np.fromiter(values.values(), dtype=np.int8, count=len(values))
    matrix = csr_matrix((data, (rows, cols)), shape=(len(user_ids), len(movie_ids)), dtype=np.int8)
    return RatingsMatrix(matrix=matrix, user_ids=user_ids, movie_ids=movie_ids)
