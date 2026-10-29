"""Grid search over CF parameters (K, LAMBDA, MIN_OVERLAP, POP_PENALTY) using ``evaluate``."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import product

from cinemate.binarize import Binarizer
from cinemate.config import RecommenderSettings
from cinemate.evaluation.runner import (
    MethodMetrics,
    NewUserPick,
    NewUserSeen,
    Split,
    established_users_line,
    evaluate_seeds,
    format_metric_cells,
    metric_headers,
    new_users_line,
)
from cinemate.movielens import Rating
from cinemate.recommender.taste import MovieFeatures

GRID_KEYS = ("k", "lam", "min_overlap", "pop_penalty", "significance")
DEFAULT_GRID = {"pop_penalty": [1.0], "significance": [0]}
DEFAULT_TASTE_GRID = {"taste_weight": [0.0, 0.25, 0.5, 1.0], "taste_interest_weight": [0.0, 0.5]}


@dataclass(frozen=True)
class TuneRow:
    """CF metrics for one parameter combination."""

    k: int
    lam: float
    min_overlap: int
    metrics: MethodMetrics
    pop_penalty: float = 1.0
    significance: int = 0


@dataclass(frozen=True)
class TasteRow:
    """``cf+taste`` metrics for one ``(taste_weight, taste_interest_weight)`` combination."""

    taste_weight: float
    taste_interest_weight: float
    metrics: MethodMetrics


@dataclass(frozen=True)
class TuneResult:
    """Rows sorted by precision@k (descending), all baselines and the evaluated user count."""

    rows: list[TuneRow]
    baselines: dict[str, MethodMetrics]
    n_users: int
    new_user_ratings: int | None = None
    seeds: tuple[int, ...] = (0,)
    new_user_pick: NewUserPick = "random"
    new_user_seen: NewUserSeen = "all"
    user_fraction: float = 1.0
    established_users: tuple[int, int] | None = None
    taste_rows: tuple[TasteRow, ...] = ()

    @property
    def baseline(self) -> MethodMetrics:
        """The original ``popular`` baseline (kept for backward compatibility)."""
        return self.baselines["popular"]


def tune(
    train: Iterable[Rating],
    test: Iterable[Rating],
    binarizer: Binarizer,
    grid: Mapping[str, Sequence[float]],
    top_n: int = 10,
    new_user_ratings: int | None = None,
    seed: int = 0,
    settings: RecommenderSettings | None = None,
    extra_splits: Sequence[Split] = (),
    new_user_pick: NewUserPick = "random",
    new_user_seen: NewUserSeen = "all",
    blend_full_at: Sequence[float] = (),
    user_fraction: float = 1.0,
    features: Mapping[int | str, MovieFeatures] | None = None,
    taste_grid: Mapping[str, Sequence[float]] | None = None,
) -> TuneResult:
    """Evaluate CF for every combination in ``grid`` (keys ``k``, ``lam``, ``min_overlap``,
    ``pop_penalty``, ``significance``; the last two are optional and default to ``[1.0]`` and
    ``[0]``).

    Each combination is evaluated once. Rows are sorted by precision@``top_n`` descending;
    ties keep grid order. The baselines do not depend on the parameters, so they are taken
    from the first evaluation. ``new_user_ratings`` and ``seed`` are passed to ``evaluate``
    (cold-start mode); ``settings`` configures the ``product`` baseline. An empty grid (any
    list empty) gives no rows and zero metrics.

    ``train``/``test`` with ``seed`` form the first split; ``extra_splits`` add more seeds.
    Every combination is evaluated on each split and the metrics are averaged (precision,
    recall and hit rate also get a standard deviation); rows sort by mean precision.
    ``new_user_pick``, ``new_user_seen``, ``blend_full_at`` (``hybrid(T=...)`` baseline rows)
    and ``user_fraction`` are passed to ``evaluate`` (see there).

    With ``features`` the best CF row is re-evaluated as ``cf+taste`` for every combination of
    ``taste_grid`` (keys ``taste_weight`` and ``taste_interest_weight``; defaults: weights
    0, 0.25, 0.5, 1 and interest weights 0, 0.5) and the results land in ``taste_rows``.
    """
    grid = {**DEFAULT_GRID, **grid}
    missing = [key for key in GRID_KEYS if key not in grid]
    if missing:
        raise ValueError(f"grid is missing keys: {', '.join(missing)}")
    splits = [Split(seed, list(train), list(test)), *extra_splits]
    rows: list[TuneRow] = []
    baselines = {"popular": MethodMetrics(0.0, 0.0, 0.0, 0.0)}
    n_users = 0
    established: tuple[int, int] | None = None
    for i, (k, lam, min_overlap, pop_penalty, significance) in enumerate(
        product(*(grid[key] for key in GRID_KEYS))
    ):
        result = evaluate_seeds(
            splits, binarizer, k=int(k), lam=float(lam), min_overlap=int(min_overlap),
            top_n=top_n, pop_penalty=float(pop_penalty), significance=int(significance),
            new_user_ratings=new_user_ratings, settings=settings,
            new_user_pick=new_user_pick, new_user_seen=new_user_seen,
            blend_full_at=blend_full_at, user_fraction=user_fraction,
        )  # fmt: skip
        if i == 0:
            baselines, n_users = result.baselines, result.n_users
            established = result.established_users
        rows.append(
            TuneRow(
                int(k), float(lam), int(min_overlap), result.cf, float(pop_penalty),
                int(significance),
            )
        )  # fmt: skip
    rows.sort(key=lambda r: -r.metrics.precision_at_k)
    taste_rows: list[TasteRow] = []
    if features is not None and rows:
        taste_grid = {**DEFAULT_TASTE_GRID, **(taste_grid or {})}
        best = rows[0]
        for gamma, interest in product(
            taste_grid["taste_weight"], taste_grid["taste_interest_weight"]
        ):
            result = evaluate_seeds(
                splits, binarizer, k=best.k, lam=best.lam, min_overlap=best.min_overlap,
                top_n=top_n, pop_penalty=best.pop_penalty, significance=best.significance,
                new_user_ratings=new_user_ratings,
                settings=replace(
                    settings or RecommenderSettings(),
                    taste_weight=float(gamma),
                    taste_interest_weight=float(interest),
                ),
                new_user_pick=new_user_pick, new_user_seen=new_user_seen,
                user_fraction=user_fraction, features=features,
            )  # fmt: skip
            taste_rows.append(TasteRow(float(gamma), float(interest), result.baselines["cf+taste"]))
    return TuneResult(
        rows=rows,
        baselines=baselines,
        n_users=n_users,
        new_user_ratings=new_user_ratings,
        seeds=tuple(s.seed for s in splits),
        new_user_pick=new_user_pick,
        new_user_seen=new_user_seen,
        user_fraction=user_fraction,
        established_users=established,
        taste_rows=tuple(taste_rows),
    )


def format_tune_table(result: TuneResult, top_n: int = 10) -> str:
    """Render ``result`` as a text table: parameters and CF metrics, then one row per baseline."""
    headers = [
        "K",
        "lambda",
        "min_overlap",
        "pop_penalty",
        "signif",
        *metric_headers(top_n),
    ]

    multi = len(result.seeds) > 1

    def metric_cells(m: MethodMetrics) -> list[str]:
        return format_metric_cells(m, multi)

    table = [
        [
            str(r.k),
            f"{r.lam:g}",
            str(r.min_overlap),
            f"{r.pop_penalty:g}",
            str(r.significance),
            *metric_cells(r.metrics),
        ]
        for r in result.rows
    ]
    table += [[name, "-", "-", "-", "-", *metric_cells(m)] for name, m in result.baselines.items()]
    widths = [max(len(row[i]) for row in [headers, *table]) for i in range(len(headers))]
    lines = ["  ".join(h.rjust(w) for h, w in zip(headers, widths, strict=True))]
    lines += ["  ".join(c.rjust(w) for c, w in zip(row, widths, strict=True)) for row in table]
    if result.taste_rows:
        lines.append("")
        lines.append("cf+taste (best CF parameters above):")
        taste_headers = ["gamma", "w_i", *metric_headers(top_n)]
        taste_table = [
            [f"{r.taste_weight:g}", f"{r.taste_interest_weight:g}", *metric_cells(r.metrics)]
            for r in result.taste_rows
        ]
        taste_widths = [
            max(len(row[i]) for row in [taste_headers, *taste_table])
            for i in range(len(taste_headers))
        ]
        lines.append(
            "  ".join(h.rjust(w) for h, w in zip(taste_headers, taste_widths, strict=True))
        )
        lines += [
            "  ".join(c.rjust(w) for c, w in zip(row, taste_widths, strict=True))
            for row in taste_table
        ]
    lines.append("")
    lines.append(f"users evaluated: {result.n_users}")
    lines.append(f"seeds: {','.join(map(str, result.seeds))}")
    if result.new_user_ratings is not None:
        lines.append(
            new_users_line(result.new_user_ratings, result.new_user_pick, result.new_user_seen)
        )
    extra = established_users_line(result.user_fraction, result.established_users)
    if extra:
        lines.append(extra)
    return "\n".join(lines)
