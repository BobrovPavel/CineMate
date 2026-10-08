"""Recommendations for a database user: movies, scores and honest explanations.

No web framework is used here. The session is only read from.
"""

import random
from dataclasses import dataclass, field
from typing import Literal

from scipy.sparse import csr_matrix, vstack
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, SeenMark, User
from cinemate.recommender.explain import explain
from cinemate.recommender.similarity import find_neighbors
from cinemate.recommender.strategy import recommend_with_strategy

# Marks that remove a movie from the results; ``not_seen`` is only a signal (VISION.md).
EXCLUDING_MARKS = ("watched", "not_interested")
NEIGHBORS_K = 40
MIN_OVERLAP = 5


@dataclass(frozen=True)
class RecommendedMovie:
    """A recommended movie with its score and explanation.

    For the fallback strategy ``liked_by`` is 0 and ``because_of`` is empty.
    """

    movie: Movie
    score: float
    liked_by: int = 0
    because_of: list[Movie] = field(default_factory=list)


@dataclass(frozen=True)
class RecommendationsResult:
    strategy: Literal["collaborative", "fallback"]
    items: list[RecommendedMovie]


def get_recommendations(
    session: Session,
    store: MatrixStore,
    user: User,
    limit: int = 20,
    rng: random.Random | None = None,
) -> RecommendationsResult:
    """Recommend up to ``limit`` movies to ``user`` using the matrix cached in ``store``.

    A user absent from the matrix gets the fallback. Movies marked ``watched`` or
    ``not_interested`` are excluded; ``not_seen`` does not exclude. Collaborative items carry
    ``liked_by`` and up to 3 ``because_of`` movies; fallback items carry neither.
    """
    if limit <= 0:
        return RecommendationsResult(strategy="fallback", items=[])

    data = store.get()
    matrix: csr_matrix = data.matrix
    if user.id in data.user_ids:
        user_index = data.user_ids.index(user.id)
    else:
        user_index = matrix.shape[0]
        matrix = vstack([matrix, csr_matrix((1, matrix.shape[1]), dtype=matrix.dtype)]).tocsr()

    excluded_ids = set(
        session.scalars(
            select(SeenMark.movie_id).where(
                SeenMark.user_id == user.id, SeenMark.type.in_(EXCLUDING_MARKS)
            )
        )
    )
    excluded_cols = {i for i, movie_id in enumerate(data.movie_ids) if movie_id in excluded_ids}

    # Over-fetch so that filtering excluded movies still leaves ``limit`` items.
    rec = recommend_with_strategy(
        matrix,
        user_index,
        n=limit + len(excluded_cols),
        k=NEIGHBORS_K,
        min_overlap=MIN_OVERLAP,
        rng=rng,
    )
    picked = [(j, s) for j, s in rec.items if j not in excluded_cols][:limit]

    neighbors = (
        find_neighbors(matrix, user_index, k=NEIGHBORS_K, min_overlap=MIN_OVERLAP)
        if rec.strategy == "collaborative"
        else []
    )
    explanations = {j: explain(matrix, user_index, j, neighbors) for j, _ in picked}

    needed = {data.movie_ids[j] for j, _ in picked}
    for exp in explanations.values():
        needed.update(data.movie_ids[b] for b in exp.because_of)
    movies = {m.id: m for m in session.scalars(select(Movie).where(Movie.id.in_(needed)))}

    items = [
        RecommendedMovie(
            movie=movies[data.movie_ids[j]],
            score=score,
            liked_by=explanations[j].liked_by if neighbors else 0,
            because_of=[movies[data.movie_ids[b]] for b in explanations[j].because_of]
            if neighbors
            else [],
        )
        for j, score in picked
    ]
    return RecommendationsResult(strategy=rec.strategy, items=items)
