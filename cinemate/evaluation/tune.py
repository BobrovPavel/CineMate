"""Grid search over CF parameters (K, LAMBDA, MIN_OVERLAP) using ``evaluate``."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import product

from cinemate.binarize import Binarizer
from cinemate.evaluation.runner import MethodMetrics, evaluate
from cinemate.movielens import Rating

GRID_KEYS = ("k", "lam", "min_overlap")


@dataclass(frozen=True)
class TuneRow:
    """CF metrics for one parameter combination."""

    k: int
    lam: float
    min_overlap: int
    metrics: MethodMetrics


@dataclass(frozen=True)
class TuneResult:
    """Rows sorted by precision@k (descending), the baseline and the evaluated user count."""

    rows: list[TuneRow]
    baseline: MethodMetrics
    n_users: int


def tune(
    train: Iterable[Rating],
    test: Iterable[Rating],
    binarizer: Binarizer,
    grid: Mapping[str, Sequence[float]],
    top_n: int = 10,
) -> TuneResult:
    """Evaluate CF for every combination in ``grid`` (keys ``k``, ``lam``, ``min_overlap``).

    Each combination is evaluated once. Rows are sorted by precision@``top_n`` descending;
    ties keep grid order. The baseline does not depend on the parameters, so it is taken
    from the first evaluation. An empty grid (any list empty) gives no rows and zero metrics.
    """
    missing = [key for key in GRID_KEYS if key not in grid]
    if missing:
        raise ValueError(f"grid is missing keys: {', '.join(missing)}")
    train = list(train)
    test = list(test)
    rows: list[TuneRow] = []
    baseline = MethodMetrics(0.0, 0.0, 0.0, 0.0)
    n_users = 0
    for i, (k, lam, min_overlap) in enumerate(product(*(grid[key] for key in GRID_KEYS))):
        result = evaluate(
            train, test, binarizer, k=int(k), lam=float(lam), min_overlap=int(min_overlap),
            top_n=top_n,
        )  # fmt: skip
        if i == 0:
            baseline, n_users = result.baseline, result.n_users
        rows.append(TuneRow(int(k), float(lam), int(min_overlap), result.cf))
    rows.sort(key=lambda r: -r.metrics.precision_at_k)
    return TuneResult(rows=rows, baseline=baseline, n_users=n_users)


def format_tune_table(result: TuneResult, top_n: int = 10) -> str:
    """Render ``result`` as a text table: parameters and CF metrics, then the baseline row."""
    headers = [
        "K",
        "lambda",
        "min_overlap",
        f"precision@{top_n}",
        f"recall@{top_n}",
        "coverage",
        "mean popularity",
    ]

    def metric_cells(m: MethodMetrics) -> list[str]:
        values = (m.precision_at_k, m.recall_at_k, m.coverage, m.mean_popularity)
        return [f"{v:.4f}" for v in values]

    table = [
        [str(r.k), f"{r.lam:g}", str(r.min_overlap), *metric_cells(r.metrics)] for r in result.rows
    ]
    table.append(["popular", "-", "-", *metric_cells(result.baseline)])
    widths = [max(len(row[i]) for row in [headers, *table]) for i in range(len(headers))]
    lines = ["  ".join(h.rjust(w) for h, w in zip(headers, widths, strict=True))]
    lines += ["  ".join(c.rjust(w) for c, w in zip(row, widths, strict=True)) for row in table]
    lines.append("")
    lines.append(f"users evaluated: {result.n_users}")
    return "\n".join(lines)
