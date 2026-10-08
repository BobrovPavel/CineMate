"""Offline evaluation: user-based CF against a deterministic "popular" baseline."""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix

from cinemate.binarize import Binarizer
from cinemate.evaluation.metrics import coverage, mean_popularity, precision_at_k
from cinemate.movielens import Rating
from cinemate.recommender.fallback import DEFAULT_MIN_RATINGS
from cinemate.recommender.matrix import build_matrix
from cinemate.recommender.scoring import recommend


@dataclass(frozen=True)
class MethodMetrics:
    """Metrics of one method, averaged over the evaluated users."""

    precision_at_k: float
    recall_at_k: float
    coverage: float
    mean_popularity: float


@dataclass(frozen=True)
class EvaluationResult:
    """Metrics of both methods plus the number of evaluated users."""

    cf: MethodMetrics
    baseline: MethodMetrics
    n_users: int


def popular_baseline(
    matrix: csr_matrix,
    exclude: Iterable[int],
    n: int = 10,
    min_ratings: int = DEFAULT_MIN_RATINGS,
) -> list[int]:
    """Deterministic top-``n`` movie indices by share of likes, without shuffling.

    Only movies with at least ``min_ratings`` ratings are considered and movies in
    ``exclude`` are skipped. Ties: more ratings first, then lower movie index.
    """
    if n <= 0:
        return []
    values = matrix.astype(np.float64)
    values.eliminate_zeros()
    totals = np.asarray(values.getnnz(axis=0)).ravel()
    likes = np.asarray((values > 0).sum(axis=0)).ravel()
    candidates = np.flatnonzero(totals >= min_ratings)
    candidates = candidates[~np.isin(candidates, list(exclude))]
    order = sorted(candidates, key=lambda m: (-likes[m] / totals[m], -totals[m], m))
    return [int(m) for m in order[:n]]


def evaluate(
    train: Iterable[Rating],
    test: Iterable[Rating],
    binarizer: Binarizer,
    k: int = 40,
    lam: float = 5.0,
    min_overlap: int = 5,
    top_n: int = 10,
) -> EvaluationResult:
    """Compare ``recommend`` (CF) with the popular baseline on a train/test split.

    The matrix is built from ``train`` only. Every user who is in the train matrix and has
    at least one liked movie (per ``binarizer``) in ``test`` is evaluated: both methods give
    ``top_n`` movies, never including anything the user rated in ``train`` (even ratings the
    binarizer discarded). Precision/recall are computed at ``top_n`` against the user's
    test likes, which may include movies unseen in train (they can never be recommended).
    The baseline only considers movies with at least ``DEFAULT_MIN_RATINGS`` (5) ratings in
    ``train``, so on tiny datasets it can be empty.
    Coverage is measured over the train catalogue; popularity of a movie is the share of train
    users who liked it. All metrics are averaged over users (coverage is global).
    With no evaluable users all metrics are ``0.0``.
    """
    train = list(train)
    built = build_matrix(train, binarizer)
    matrix = built.matrix
    user_index = {u: i for i, u in enumerate(built.user_ids)}
    movie_index = {m: i for i, m in enumerate(built.movie_ids)}

    seen: dict[int, set[int]] = defaultdict(set)
    for r in train:
        seen[r.user_id].add(r.movie_id)
    test_likes: dict[int, set[int]] = defaultdict(set)
    for r in test:
        if binarizer.binarize(r.score) == 1:
            test_likes[r.user_id].add(r.movie_id)

    n_movies = len(built.movie_ids)
    n_train_users = len(built.user_ids)
    like_counts = np.asarray((matrix > 0).sum(axis=0)).ravel()
    popularity = {
        m: float(like_counts[m]) / n_train_users for m in range(n_movies) if n_train_users
    }

    def cf(u: int, exclude: set[int]) -> list[int]:
        recs = recommend(matrix, u, n=n_movies, k=k, min_overlap=min_overlap, lam=lam)
        return [m for m, _ in recs if m not in exclude][:top_n]

    def baseline(_u: int, exclude: set[int]) -> list[int]:
        return popular_baseline(matrix, exclude, n=top_n)

    methods: dict[str, Callable[[int, set[int]], list[int]]] = {"cf": cf, "baseline": baseline}
    lists: dict[str, list[list[int]]] = {name: [] for name in methods}
    precisions: dict[str, list[float]] = {name: [] for name in methods}
    recalls: dict[str, list[float]] = {name: [] for name in methods}
    pops: dict[str, list[float]] = {name: [] for name in methods}

    n_users = 0
    for user_id in sorted(test_likes):
        if user_id not in user_index:
            continue
        n_users += 1
        u = user_index[user_id]
        exclude = {movie_index[m] for m in seen[user_id] if m in movie_index}
        relevant = {movie_index[m] for m in test_likes[user_id] if m in movie_index}
        # Test likes unseen in train still count in the recall denominator.
        n_relevant = len(test_likes[user_id])
        for name, method in methods.items():
            recs = method(u, exclude)
            lists[name].append(recs)
            precisions[name].append(precision_at_k(recs, relevant, top_n))
            hits = len(set(recs[:top_n]) & relevant)
            recalls[name].append(hits / n_relevant if n_relevant else 0.0)
            pops[name].append(mean_popularity(recs, popularity))

    def summarize(name: str) -> MethodMetrics:
        if n_users == 0:
            return MethodMetrics(0.0, 0.0, 0.0, 0.0)
        return MethodMetrics(
            precision_at_k=sum(precisions[name]) / n_users,
            recall_at_k=sum(recalls[name]) / n_users,
            coverage=coverage(lists[name], n_movies),
            mean_popularity=sum(pops[name]) / n_users,
        )

    return EvaluationResult(cf=summarize("cf"), baseline=summarize("baseline"), n_users=n_users)
