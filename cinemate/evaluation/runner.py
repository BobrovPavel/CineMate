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
    """CF metrics, metrics of every baseline and the number of evaluated users.

    ``baselines`` keys: ``popular`` (the original weak baseline), ``popular_likes``,
    ``popular_share_20`` and ``popular_share_50``.
    """

    cf: MethodMetrics
    baselines: dict[str, MethodMetrics]
    n_users: int

    @property
    def baseline(self) -> MethodMetrics:
        """The original ``popular`` baseline (kept for backward compatibility)."""
        return self.baselines["popular"]


def popular_baseline(
    matrix: csr_matrix,
    exclude: Iterable[int],
    n: int = 10,
    min_ratings: int = DEFAULT_MIN_RATINGS,
) -> list[int]:
    """Deterministic top-``n`` movie indices by share of likes, without shuffling.

    Only movies with at least ``min_ratings`` ratings are considered and movies in
    ``exclude`` are skipped. Ties: more ratings first, then lower movie index.

    The default threshold of 5 ratings makes this a weak opponent: obscure movies with 5 likes
    out of 5 rank first. It is kept unchanged so results stay comparable with earlier runs;
    for a fair comparison use ``popular_by_likes`` and ``popular_by_share`` with a higher
    ``min_ratings`` (20 or 50).
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


def popular_by_likes(matrix: csr_matrix, exclude: Iterable[int], n: int = 10) -> list[int]:
    """Top-``n`` movie indices by absolute number of likes (``+1``), skipping ``exclude``.

    Ties: lower movie index first.
    """
    if n <= 0:
        return []
    likes = np.asarray((matrix > 0).sum(axis=0)).ravel()
    banned = set(exclude)
    order = sorted((m for m in range(len(likes)) if m not in banned), key=lambda m: (-likes[m], m))
    return [int(m) for m in order[:n]]


def popular_by_share(
    matrix: csr_matrix, exclude: Iterable[int], n: int = 10, min_ratings: int = 20
) -> list[int]:
    """Top-``n`` movie indices by share of likes among movies with ``min_ratings`` ratings.

    Same ordering as ``popular_baseline`` (ties: more ratings, then lower index) but with a
    configurable threshold; the evaluation runs it with 20 and 50.
    """
    return popular_baseline(matrix, exclude, n=n, min_ratings=min_ratings)


def evaluate(
    train: Iterable[Rating],
    test: Iterable[Rating],
    binarizer: Binarizer,
    k: int = 40,
    lam: float = 5.0,
    min_overlap: int = 5,
    top_n: int = 10,
    pop_penalty: float = 1.0,
) -> EvaluationResult:
    """Compare ``recommend`` (CF) with the popular baseline on a train/test split.

    The matrix is built from ``train`` only. Every user who is in the train matrix and has
    at least one liked movie (per ``binarizer``) in ``test`` is evaluated: both methods give
    ``top_n`` movies, never including anything the user rated in ``train`` (even ratings the
    binarizer discarded). Precision/recall are computed at ``top_n`` against the user's
    test likes, which may include movies unseen in train (they can never be recommended).
    The ``popular`` baseline only considers movies with at least ``DEFAULT_MIN_RATINGS`` (5)
    ratings in ``train``, so on tiny datasets it can be empty. Stronger baselines are reported
    too: ``popular_likes`` (most likes), ``popular_share_20`` and ``popular_share_50`` (share of
    likes with at least 20 / 50 ratings). Each baseline list is the same for every user before
    excluding the user's train movies.
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
        recs = recommend(
            matrix,
            u,
            n=n_movies,
            k=k,
            min_overlap=min_overlap,
            lam=lam,
            pop_penalty=pop_penalty,
        )
        return [m for m, _ in recs if m not in exclude][:top_n]

    methods: dict[str, Callable[[int, set[int]], list[int]]] = {
        "cf": cf,
        "popular": lambda _u, exclude: popular_baseline(matrix, exclude, n=top_n),
        "popular_likes": lambda _u, exclude: popular_by_likes(matrix, exclude, n=top_n),
        "popular_share_20": lambda _u, exclude: popular_by_share(
            matrix, exclude, n=top_n, min_ratings=20
        ),
        "popular_share_50": lambda _u, exclude: popular_by_share(
            matrix, exclude, n=top_n, min_ratings=50
        ),
    }
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

    return EvaluationResult(
        cf=summarize("cf"),
        baselines={name: summarize(name) for name in methods if name != "cf"},
        n_users=n_users,
    )
