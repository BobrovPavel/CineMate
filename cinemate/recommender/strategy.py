"""Single entry point choosing between collaborative filtering and the fallback."""

import random
from dataclasses import dataclass
from typing import Literal

from scipy.sparse import csr_matrix

from cinemate.recommender.fallback import DEFAULT_POOL_FACTOR, popular
from cinemate.recommender.hybrid import recommend_hybrid_detailed
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
    pop_penalty: float = 1.0,
    significance: int = 0,
    min_user_ratings: int = MIN_USER_RATINGS,
    fallback_pool_factor: int = DEFAULT_POOL_FACTOR,
    rng: random.Random | None = None,
    blend_full_at: float = 0.0,
    neighbors: list[tuple[int, float]] | None = None,
) -> Recommendation:
    """Recommend collaboratively, falling back to popular movies when data is too thin.

    The fallback is used if the user has fewer than ``min_user_ratings`` ratings or
    ``recommend`` returns nothing. ``fallback_pool_factor`` is passed to ``popular``.

    With ``blend_full_at > 0`` the hybrid (``recommend_hybrid``) is used instead and the
    threshold logic is skipped; the strategy is ``collaborative`` if its CF weight is at least
    0.5 and the user has neighbours, otherwise ``fallback``. ``0`` keeps the threshold logic.
    Precomputed ``neighbors`` are used by the threshold logic only, to save a second search.
    """
    if blend_full_at > 0:
        hybrid = recommend_hybrid_detailed(
            matrix,
            user_index,
            n=n,
            k=k,
            min_overlap=min_overlap,
            lam=lam,
            blend_full_at=blend_full_at,
            significance=significance,
        )
        collaborative = hybrid.beta >= 0.5 and hybrid.has_neighbors
        return Recommendation(
            items=hybrid.items, strategy="collaborative" if collaborative else "fallback"
        )
    row = matrix[user_index].copy()
    row.eliminate_zeros()
    if row.nnz >= min_user_ratings:
        items = recommend(
            matrix,
            user_index,
            n=n,
            k=k,
            min_overlap=min_overlap,
            lam=lam,
            pop_penalty=pop_penalty,
            significance=significance,
            neighbors=neighbors,
        )
        if items:
            return Recommendation(items=items, strategy="collaborative")
    return Recommendation(
        items=popular(matrix, user_index, n=n, pool_factor=fallback_pool_factor, rng=rng),
        strategy="fallback",
    )
