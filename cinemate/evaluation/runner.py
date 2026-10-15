"""Offline evaluation: user-based CF against a deterministic "popular" baseline."""

import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.sparse import csr_matrix

from cinemate.binarize import Binarizer
from cinemate.config import RecommenderSettings
from cinemate.evaluation.metrics import (
    coverage,
    hit_rate_at_k,
    mean_popularity,
    precision_at_k,
)
from cinemate.movielens import Rating
from cinemate.recommender.hybrid import recommend_hybrid
from cinemate.recommender.item_based import recommend_item_based
from cinemate.recommender.matrix import build_matrix
from cinemate.recommender.scoring import recommend
from cinemate.recommender.strategy import recommend_with_strategy
from cinemate.services.onboarding import pick_onboarding_movies

# Threshold of the weak ``popular`` baseline; fixed so results stay comparable with earlier runs.
DEFAULT_MIN_RATINGS = 5

NewUserPick = Literal["random", "onboarding"]
NewUserSeen = Literal["all", "kept"]
ONBOARDING_POOL = 300


@dataclass(frozen=True)
class MethodMetrics:
    """Metrics of one method, averaged over the evaluated users.

    The ``*_std`` fields are the sample standard deviation (``ddof=1``) over several seeds;
    they stay ``0.0`` for a single run.
    """

    precision_at_k: float
    recall_at_k: float
    coverage: float
    mean_popularity: float
    hit_rate_at_k: float = 0.0
    precision_std: float = 0.0
    recall_std: float = 0.0
    hit_rate_std: float = 0.0


@dataclass(frozen=True)
class EvaluationResult:
    """CF metrics, metrics of every baseline and the number of evaluated users.

    ``baselines`` keys: ``popular`` (the original weak baseline), ``popular_likes``,
    ``popular_share_20``, ``popular_share_50`` and ``product`` (CF with the fallback, as on the
    site). ``new_user_ratings`` is set when only "new" users with that many ratings were evaluated.
    """

    cf: MethodMetrics
    baselines: dict[str, MethodMetrics]
    n_users: int
    new_user_ratings: int | None = None
    seeds: tuple[int, ...] = (0,)
    new_user_pick: NewUserPick = "random"
    new_user_seen: NewUserSeen = "all"
    user_fraction: float = 1.0
    established_users: tuple[int, int] | None = None

    @property
    def baseline(self) -> MethodMetrics:
        """The original ``popular`` baseline (kept for backward compatibility)."""
        return self.baselines["popular"]


@dataclass(frozen=True)
class Split:
    """One train/test split together with the seed it was made with."""

    seed: int
    train: list[Rating]
    test: list[Rating]


def aggregate_metrics(runs: Sequence[MethodMetrics]) -> MethodMetrics:
    """Mean of every metric over ``runs``; precision/recall/hit rate also get a sample std."""
    if not runs:
        raise ValueError("runs must not be empty")

    def mean(field: str) -> float:
        return statistics.fmean(getattr(r, field) for r in runs)

    def std(field: str) -> float:
        if len(runs) < 2:
            return 0.0
        return statistics.stdev(getattr(r, field) for r in runs)

    return MethodMetrics(
        precision_at_k=mean("precision_at_k"),
        recall_at_k=mean("recall_at_k"),
        coverage=mean("coverage"),
        mean_popularity=mean("mean_popularity"),
        hit_rate_at_k=mean("hit_rate_at_k"),
        precision_std=std("precision_at_k"),
        recall_std=std("recall_at_k"),
        hit_rate_std=std("hit_rate_at_k"),
    )


def format_metric_cells(m: MethodMetrics, with_std: bool) -> list[str]:
    """Cells: precision, recall, hit rate (``mean±std`` if ``with_std``), coverage, popularity."""
    cells = [
        f"{value:.4f}±{std:.4f}" if with_std else f"{value:.4f}"
        for value, std in (
            (m.precision_at_k, m.precision_std),
            (m.recall_at_k, m.recall_std),
            (m.hit_rate_at_k, m.hit_rate_std),
        )
    ]
    return [*cells, f"{m.coverage:.4f}", f"{m.mean_popularity:.4f}"]


def new_users_line(n_ratings: int, pick: NewUserPick, seen: NewUserSeen = "all") -> str:
    """Table line describing the cold-start mode.

    The text is unchanged for the ``random`` pick with ``seen="all"``; ``seen="kept"`` adds
    ``seen: kept`` to the parenthesis (with ``pick`` too when it is not ``random``).
    """
    parts = []
    if pick != "random" or seen != "all":
        parts.append(f"pick: {pick}")
    if seen != "all":
        parts.append(f"seen: {seen}")
    suffix = f" ({', '.join(parts)})" if parts else ""
    return f"new users: {n_ratings} ratings each{suffix}"


def established_users_line(user_fraction: float, established: tuple[int, int] | None) -> str | None:
    """Table line ``established users: <kept> of <total> (fraction F)``; ``None`` at ``F = 1``."""
    if user_fraction >= 1.0 or established is None:
        return None
    kept, total = established
    return f"established users: {kept} of {total} (fraction {user_fraction:g})"


def parse_seeds(text: str) -> list[int]:
    """Parse ``0,1,2``; raise ``ValueError`` on an empty list, bad numbers or duplicates."""
    try:
        seeds = [int(p) for p in text.split(",")]
    except ValueError:
        raise ValueError(f"invalid seed list: {text!r}") from None
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"duplicate seeds in {text!r}")
    return seeds


def evaluate_seeds(
    splits: Sequence[Split],
    binarizer: Binarizer,
    **kwargs,
) -> EvaluationResult:
    """Run ``evaluate`` on every split (with ``seed=split.seed``) and aggregate the metrics.

    ``kwargs`` are passed to ``evaluate`` (except ``seed``). ``n_users`` is taken from the
    first split. Seeds must be non-empty and unique.
    """
    seeds = [s.seed for s in splits]
    if not seeds:
        raise ValueError("at least one seed is required")
    if len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be unique")
    results = [evaluate(s.train, s.test, binarizer, seed=s.seed, **kwargs) for s in splits]
    first = results[0]
    return EvaluationResult(
        cf=aggregate_metrics([r.cf for r in results]),
        baselines={
            name: aggregate_metrics([r.baselines[name] for r in results])
            for name in first.baselines
        },
        n_users=first.n_users,
        new_user_ratings=first.new_user_ratings,
        seeds=tuple(seeds),
        new_user_pick=first.new_user_pick,
        new_user_seen=first.new_user_seen,
        user_fraction=first.user_fraction,
        established_users=first.established_users,
    )


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
    significance: int = 0,
    new_user_ratings: int | None = None,
    seed: int = 0,
    settings: RecommenderSettings | None = None,
    new_user_pick: NewUserPick = "random",
    new_user_seen: NewUserSeen = "all",
    blend_full_at: Sequence[float] = (),
    item_min_overlap: int = 3,
    item_lam: float = 5.0,
    user_fraction: float = 1.0,
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

    For every ``T`` in ``blend_full_at`` a ``hybrid(T=<T>)`` baseline runs ``recommend_hybrid``
    with that ``blend_full_at`` and the CF parameters from ``settings``; its CF weight is
    ``min(1, n / T)`` for a user with ``n`` ratings in the matrix (so ``min(1, N / T)`` in
    cold-start mode). Values must be positive.

    ``item_based`` runs ``recommend_item_based`` with ``item_min_overlap`` and ``item_lam``.

    ``product`` runs ``recommend_with_strategy`` with ``settings`` (default
    ``RecommenderSettings()``) and a fallback ``rng`` seeded by ``seed``.

    With ``new_user_ratings=N`` (cold-start mode) the train users are split by ``seed``:
    "new" users (half of those with at least ``N`` usable ratings) keep exactly ``N`` random
    usable train ratings in the matrix and are the only ones evaluated;
    the dropped ratings still count as seen (never recommended)
    but are not relevant. Users with fewer than ``N`` usable ratings are never "new".
    "Established" users keep all ratings and serve as neighbours only.

    ``new_user_pick`` chooses which ratings a "new" user keeps. ``"random"`` draws them at
    random. ``"onboarding"`` imitates the site: the cards come from ``pick_onboarding_movies``
    on the matrix of the full train set (top ``ONBOARDING_POOL`` movies by rating count, most
    controversial first), and a new user keeps their first ``N`` usable ratings in that card
    order (a "not seen" answer is a movie they did not rate). Only users with at least ``N``
    usable ratings among the cards can be "new". Genres are unknown here, so the per-genre
    limit of the onboarding picker does not apply. Requires ``new_user_ratings``.

    ``new_user_seen`` decides what is excluded from the lists of a "new" user. ``"all"`` (the
    default) excludes every train rating, including the dropped ones. ``"kept"`` imitates the
    site, which only knows what the user rated or marked: only the ``N`` ratings left in the
    matrix are excluded, so dropped train ratings may be recommended (they are still not
    relevant; only test likes are). Test ratings are never excluded. Requires ``new_user_ratings``.

    ``user_fraction`` ``F`` (``0 < F <= 1``, default ``1.0`` = no change) thins out the
    "established" (neighbour) users: a random ``F`` share of them, at least one, stays in the
    matrix and the rest are removed entirely. The set of "new" (evaluated) users does not
    depend on ``F``; thinning is deterministic for a ``seed``. It measures how CF quality
    depends on the size of the user base. Requires ``new_user_ratings``.
    """
    if new_user_ratings is not None and new_user_ratings < 1:
        raise ValueError("new_user_ratings must be at least 1")
    if new_user_pick not in ("random", "onboarding"):
        raise ValueError(f"unknown new_user_pick: {new_user_pick!r}")
    if new_user_pick != "random" and new_user_ratings is None:
        raise ValueError("new_user_pick requires new_user_ratings")
    if new_user_seen not in ("all", "kept"):
        raise ValueError(f"unknown new_user_seen: {new_user_seen!r}")
    if new_user_seen != "all" and new_user_ratings is None:
        raise ValueError("new_user_seen requires new_user_ratings")
    if not 0 < user_fraction <= 1:
        raise ValueError("user_fraction must be in (0, 1]")
    if user_fraction != 1.0 and new_user_ratings is None:
        raise ValueError("user_fraction requires new_user_ratings")
    if any(not t > 0 for t in blend_full_at):
        raise ValueError("blend_full_at values must be > 0")
    settings = settings or RecommenderSettings()
    train = list(train)
    seen: dict[int, set[int]] = defaultdict(set)
    for r in train:
        seen[r.user_id].add(r.movie_id)
    new_users: set[int] | None = None
    established: tuple[int, int] | None = None
    if new_user_ratings is not None:
        train, new_users = _truncate_new_users(
            train, new_user_ratings, seed, binarizer, new_user_pick
        )
        if user_fraction != 1.0:
            train, established = _thin_established_users(train, new_users, user_fraction, seed)
        if new_user_seen == "kept":
            # Established users keep all ratings, new users only the ones left in the matrix.
            seen = defaultdict(set)
            for r in train:
                seen[r.user_id].add(r.movie_id)
    built = build_matrix(train, binarizer)
    matrix = built.matrix
    user_index = {u: i for i, u in enumerate(built.user_ids)}
    movie_index = {m: i for i, m in enumerate(built.movie_ids)}

    test_likes: dict[int, set[int]] = defaultdict(set)
    for r in test:
        if binarizer.binarize(r.score) == 1 and (new_users is None or r.user_id in new_users):
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
            significance=significance,
        )
        return [m for m, _ in recs if m not in exclude][:top_n]

    product_rng = random.Random(seed)

    def product(u: int, exclude: set[int]) -> list[int]:
        row = matrix[u].copy()
        row.eliminate_zeros()
        extra = len(exclude - {int(m) for m in row.indices})
        rec = recommend_with_strategy(
            matrix,
            u,
            n=top_n + extra,
            k=settings.k,
            min_overlap=settings.min_overlap,
            lam=settings.lam,
            pop_penalty=settings.pop_penalty,
            significance=settings.significance,
            min_user_ratings=settings.min_user_ratings,
            fallback_pool_factor=settings.fallback_pool_factor,
            rng=product_rng,
        )
        return [m for m, _ in rec.items if m not in exclude][:top_n]

    def hybrid(threshold: float) -> Callable[[int, set[int]], list[int]]:
        def method(u: int, exclude: set[int]) -> list[int]:
            recs = recommend_hybrid(
                matrix,
                u,
                n=n_movies,
                k=settings.k,
                min_overlap=settings.min_overlap,
                lam=settings.lam,
                blend_full_at=threshold,
                significance=settings.significance,
            )
            return [m for m, _ in recs if m not in exclude][:top_n]

        return method

    def item_based(u: int, exclude: set[int]) -> list[int]:
        recs = recommend_item_based(
            matrix, u, n=n_movies, min_overlap=item_min_overlap, lam=item_lam
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
        "product": product,
        "item_based": item_based,
        **{f"hybrid(T={t:g})": hybrid(t) for t in blend_full_at},
    }
    lists: dict[str, list[list[int]]] = {name: [] for name in methods}
    precisions: dict[str, list[float]] = {name: [] for name in methods}
    recalls: dict[str, list[float]] = {name: [] for name in methods}
    hit_rates: dict[str, list[float]] = {name: [] for name in methods}
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
            hit_rates[name].append(hit_rate_at_k(recs, relevant, top_n))
            pops[name].append(mean_popularity(recs, popularity))

    def summarize(name: str) -> MethodMetrics:
        if n_users == 0:
            return MethodMetrics(0.0, 0.0, 0.0, 0.0)
        return MethodMetrics(
            precision_at_k=sum(precisions[name]) / n_users,
            recall_at_k=sum(recalls[name]) / n_users,
            coverage=coverage(lists[name], n_movies),
            mean_popularity=sum(pops[name]) / n_users,
            hit_rate_at_k=sum(hit_rates[name]) / n_users,
        )

    return EvaluationResult(
        cf=summarize("cf"),
        baselines={name: summarize(name) for name in methods if name != "cf"},
        n_users=n_users,
        new_user_ratings=new_user_ratings,
        new_user_pick=new_user_pick,
        new_user_seen=new_user_seen,
        user_fraction=user_fraction,
        established_users=established,
    )


def _thin_established_users(
    train: list[Rating], new_users: set[int], fraction: float, seed: int
) -> tuple[list[Rating], tuple[int, int]]:
    """Keep a random ``fraction`` (at least one user) of the non-"new" users, drop the rest.

    Uses its own generator so the choice of "new" users never depends on ``fraction``.
    Returns the reduced train list and ``(kept, total)`` established users.
    """
    established = sorted({r.user_id for r in train} - new_users)
    if not established:
        return train, (0, 0)
    keep_count = min(len(established), max(1, round(fraction * len(established))))
    rng = random.Random(f"user-fraction:{seed}")
    kept = set(rng.sample(established, keep_count))
    dropped = set(established) - kept
    return [r for r in train if r.user_id not in dropped], (keep_count, len(established))


def _truncate_new_users(
    train: list[Rating],
    n_ratings: int,
    seed: int,
    binarizer: Binarizer,
    pick: NewUserPick = "random",
) -> tuple[list[Rating], set[int]]:
    """Mark half of the eligible train users as "new" and keep ``n_ratings`` of their ratings.

    Eligible users have at least ``n_ratings`` ratings that survive binarization (in
    ``onboarding`` mode: among the onboarding cards), so a new user has exactly ``n_ratings``
    entries in the matrix. The kept ratings are random binarizable ones, or the first ones in
    onboarding card order; everything else (neutral and dropped ratings) leaves the matrix.
    Returns the reduced train list and the set of new user ids; deterministic for a ``seed``.
    """
    by_user: dict[int, list[Rating]] = defaultdict(list)
    for r in train:
        by_user[r.user_id].append(r)

    def usable_indices(items: list[Rating]) -> list[int]:
        usable = [i for i, r in enumerate(items) if binarizer.binarize(r.score) is not None]
        if card_rank is None:
            return usable
        usable = [i for i in usable if items[i].movie_id in card_rank]
        return sorted(usable, key=lambda i: card_rank[items[i].movie_id])

    card_rank: dict[int, int] | None = None
    if pick == "onboarding":
        built = build_matrix(train, binarizer)
        n_movies = len(built.movie_ids)
        cards = pick_onboarding_movies(
            built.matrix, genres=[[] for _ in range(n_movies)], n=n_movies, pool=ONBOARDING_POOL
        )
        card_rank = {built.movie_ids[m]: pos for pos, m in enumerate(cards)}
    rng = random.Random(seed)
    user_ids = sorted(u for u, items in by_user.items() if len(usable_indices(items)) >= n_ratings)
    rng.shuffle(user_ids)
    new_users = set(user_ids[: len(user_ids) // 2])
    reduced: list[Rating] = []
    for user_id in sorted(by_user):
        items = by_user[user_id]
        if user_id in new_users:
            usable = usable_indices(items)
            keep = set(
                usable[:n_ratings] if card_rank is not None else rng.sample(usable, n_ratings)
            )
            items = [r for i, r in enumerate(items) if i in keep]
        reduced.extend(items)
    return reduced, new_users
