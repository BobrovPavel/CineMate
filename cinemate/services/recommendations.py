"""Recommendations for a database user: movies, scores and honest explanations.

No web framework is used here. The session is only read from.
"""

import random
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.sparse import csr_matrix, vstack
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.config import RecommenderSettings
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, SeenMark, User
from cinemate.recommender.explain import explain
from cinemate.recommender.matrix import RatingsMatrix
from cinemate.recommender.similarity import find_neighbors
from cinemate.recommender.strategy import recommend_with_strategy

# Marks that remove a movie from the results; ``not_seen`` is only a signal (VISION.md).
EXCLUDING_MARKS = ("watched", "not_interested")


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


def _with_fresh_row(session: Session, data: RatingsMatrix, user: User) -> tuple[csr_matrix, int]:
    """Return the cached matrix with ``user``'s row taken from the database, and its index.

    The cached matrix may be older than the user's latest ratings. The row is replaced (or
    appended for a user absent from the matrix); ratings of movies that are not matrix columns
    are ignored. The cached matrix itself is never modified.
    """
    matrix = data.matrix
    cols: list[int] = []
    values: list[int] = []
    for movie_id, value in session.execute(
        select(Rating.movie_id, Rating.value).where(Rating.user_id == user.id)
    ):
        col = bisect_left(data.movie_ids, movie_id)
        if col < len(data.movie_ids) and data.movie_ids[col] == movie_id:
            cols.append(col)
            values.append(value)
    fresh = csr_matrix(
        (
            np.array(values, dtype=matrix.dtype),
            (np.zeros(len(cols), dtype=int), np.array(cols, dtype=int)),
        ),
        shape=(1, matrix.shape[1]),
    )

    row = bisect_left(data.user_ids, user.id)
    if row < len(data.user_ids) and data.user_ids[row] == user.id:
        if (matrix[row] != fresh).nnz == 0:
            return matrix, row
        parts = [matrix[:row], fresh, matrix[row + 1 :]]
        return vstack(parts).tocsr(), row
    return vstack([matrix, fresh]).tocsr(), matrix.shape[0]


def get_recommendations(
    session: Session,
    store: MatrixStore,
    user: User,
    limit: int = 20,
    rng: random.Random | None = None,
    settings: RecommenderSettings | None = None,
) -> RecommendationsResult:
    """Recommend up to ``limit`` movies to ``user`` using the matrix cached in ``store``.

    The user's own row is read from the database, so their latest ratings count immediately;
    other users' ratings arrive with the store's next background rebuild.

    ``settings`` defaults to :class:`RecommenderSettings` defaults.

    A user absent from the matrix gets the fallback. Movies marked ``watched`` or
    ``not_interested`` are excluded; ``not_seen`` does not exclude. Collaborative items carry
    ``liked_by`` and up to 3 ``because_of`` movies; fallback items carry neither.
    """
    settings = settings or RecommenderSettings()
    if limit <= 0:
        return RecommendationsResult(strategy="fallback", items=[])

    data = store.get(user.pool)
    matrix, user_index = _with_fresh_row(session, data, user)

    excluded_ids = set(
        session.scalars(
            select(SeenMark.movie_id).where(
                SeenMark.user_id == user.id, SeenMark.type.in_(EXCLUDING_MARKS)
            )
        )
    )
    excluded_cols = {i for i, movie_id in enumerate(data.movie_ids) if movie_id in excluded_ids}

    neighbors = None
    if settings.blend_full_at <= 0 and int((matrix[user_index].data != 0).sum()) >= (
        settings.min_user_ratings
    ):
        # shared by the scoring and the explanations: the search is the costly step
        neighbors = find_neighbors(
            matrix,
            user_index,
            k=settings.k,
            min_overlap=settings.min_overlap,
            significance=settings.significance,
        )

    # Over-fetch so that filtering excluded movies still leaves ``limit`` items.
    rec = recommend_with_strategy(
        matrix,
        user_index,
        n=limit + len(excluded_cols),
        k=settings.k,
        min_overlap=settings.min_overlap,
        lam=settings.lam,
        pop_penalty=settings.pop_penalty,
        significance=settings.significance,
        min_user_ratings=settings.min_user_ratings,
        fallback_pool_factor=settings.fallback_pool_factor,
        blend_full_at=settings.blend_full_at,
        rng=rng,
        neighbors=neighbors,
    )
    picked = [(j, s) for j, s in rec.items if j not in excluded_cols][:limit]

    if rec.strategy != "collaborative":
        neighbors = []
    elif neighbors is None:
        neighbors = find_neighbors(
            matrix,
            user_index,
            k=settings.k,
            min_overlap=settings.min_overlap,
            significance=settings.significance,
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
