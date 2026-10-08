import argparse
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from cinemate import __version__
from cinemate.binarize import MovieLensBinarizer
from cinemate.datasets import DEFAULT_DATA_DIR, ensure_movielens
from cinemate.db.importer import import_movielens
from cinemate.db.session import create_all, make_engine
from cinemate.evaluation.metrics import split_ratings
from cinemate.evaluation.runner import EvaluationResult, MethodMetrics, evaluate
from cinemate.movielens import parse_ratings


def format_table(result: EvaluationResult, top_n: int = 10) -> str:
    """Render ``result`` as a text table: one row per method, then the user count."""
    headers = [f"precision@{top_n}", f"recall@{top_n}", "coverage", "mean popularity"]
    rows = [("collaborative", result.cf), ("popular", result.baseline)]

    def cells(m: MethodMetrics) -> list[str]:
        values = (m.precision_at_k, m.recall_at_k, m.coverage, m.mean_popularity)
        return [f"{v:.4f}" for v in values]

    name_width = max(len(name) for name, _ in rows)
    widths = [len(h) for h in headers]
    lines = [
        " " * name_width
        + "  "
        + "  ".join(h.rjust(w) for h, w in zip(headers, widths, strict=True))
    ]
    for name, metrics in rows:
        line = "  ".join(c.rjust(w) for c, w in zip(cells(metrics), widths, strict=True))
        lines.append(f"{name.ljust(name_width)}  {line}")
    lines.append("")
    lines.append(f"users evaluated: {result.n_users}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cinemate")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    ev = sub.add_parser("evaluate", help="evaluate CF against the popular baseline on MovieLens")
    ev.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="where MovieLens is stored or downloaded to (default: %(default)s)",
    )
    ev.add_argument("--k", type=int, default=40, help="number of neighbours (default: %(default)s)")
    ev.add_argument(
        "--lambda",
        dest="lam",
        type=float,
        default=5.0,
        help="shrinkage strength (default: %(default)s)",
    )
    ev.add_argument(
        "--min-overlap",
        type=int,
        default=5,
        help="minimum co-rated movies for a neighbour (default: %(default)s)",
    )
    ev.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="recommendations per user, also the cut-off for precision/recall "
        "(default: %(default)s)",
    )
    ev.add_argument(
        "--seed", type=int, default=0, help="train/test split seed (default: %(default)s)"
    )
    imp = sub.add_parser("import-movielens", help="import MovieLens into the database")
    imp.add_argument(
        "--database-url",
        default="sqlite:///cinemate.db",
        help="SQLAlchemy database URL (default: %(default)s)",
    )
    imp.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="where MovieLens is stored or downloaded to (default: %(default)s)",
    )
    return parser


def _run_import(args: argparse.Namespace) -> int:
    dataset = ensure_movielens(args.data_dir)
    engine = make_engine(args.database_url)
    create_all(engine)
    with Session(engine) as session:
        stats = import_movielens(session, dataset, MovieLensBinarizer())
    print(
        f"movies added: {stats.movies_added}, users added: {stats.users_added}, "
        f"ratings added: {stats.ratings_added}, ratings skipped: {stats.ratings_skipped}"
    )
    return 0


def _run_evaluate(args: argparse.Namespace) -> int:
    dataset = ensure_movielens(args.data_dir)
    ratings = list(parse_ratings(dataset / "ratings.csv"))
    train, test = split_ratings(ratings, seed=args.seed)
    result = evaluate(
        train,
        test,
        MovieLensBinarizer(),
        k=args.k,
        lam=args.lam,
        min_overlap=args.min_overlap,
        top_n=args.top_n,
    )
    print(format_table(result, args.top_n))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "evaluate":
        return _run_evaluate(args)
    if args.command == "import-movielens":
        return _run_import(args)
    return 0
