"""Single entry point choosing between collaborative filtering and the fallback."""

import random
from dataclasses import dataclass
from typing import Literal

from scipy.sparse import csr_matrix

from cinemate.recommender.fallback import popular
from cinemate.recommender.scoring import recommend

MIN_USER_RATINGS = 5


@dataclass(frozen=True)
class Recommendation:
    """Recommended ``(movie_index, score)`` pairs and the strategy that produced them."""

    items: list[tuple[int, float]]
    strategy: Literal["collaborative", "fallback"]


def recommend_with_strategy(
    matrix: csr_matrix,
    user_index: int,
    n: int = 20,
    k: int = 40,
    min_overlap: int = 5,
    lam: float = 5.0,
    min_user_ratings: int = MIN_USER_RATINGS,
    rng: random.Random | None = None,
) -> Recommendation:
    """Recommend collaboratively, falling back to popular movies when data is too thin.

    The fallback is used if the user has fewer than ``min_user_ratings`` ratings or
    ``recommend`` returns nothing.
    """
    row = matrix[user_index].copy()
    row.eliminate_zeros()
    if row.nnz >= min_user_ratings:
        items = recommend(matrix, user_index, n=n, k=k, min_overlap=min_overlap, lam=lam)
        if items:
            return Recommendation(items=items, strategy="collaborative")
    return Recommendation(items=popular(matrix, user_index, n=n, rng=rng), strategy="fallback")
