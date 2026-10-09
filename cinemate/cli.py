import argparse
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from cinemate import __version__
from cinemate.binarize import MovieLensBinarizer
from cinemate.datasets import DEFAULT_DATA_DIR, ensure_movielens
from cinemate.db.enrich import enrich_movies
from cinemate.db.importer import import_movielens
from cinemate.db.session import create_all, make_engine
from cinemate.evaluation.metrics import split_ratings
from cinemate.evaluation.runner import EvaluationResult, MethodMetrics, evaluate
from cinemate.evaluation.tune import format_tune_table, tune
from cinemate.movielens import parse_ratings
from cinemate.services.metrics import good_session_rate, good_session_rate_by_strategy, retention_7d
from cinemate.tmdb import TmdbClient, TmdbError

DEFAULT_DATABASE_URL = "sqlite:///cinemate.db"
_DATABASE_URL_HELP = (
    f"SQLAlchemy database URL (default: env DATABASE_URL, else {DEFAULT_DATABASE_URL})"
)


def resolve_database_url(arg: str | None) -> str:
    """Pick the database URL: the argument, then env ``DATABASE_URL``, then the default."""
    return arg or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def _open_engine(args: argparse.Namespace) -> Engine | None:
    """Create the engine and schema; on a bad URL print an error without echoing the URL."""
    try:
        engine = make_engine(resolve_database_url(args.database_url))
    except (ArgumentError, ImportError):
        print(f"cinemate {args.command}: error: invalid database URL", file=sys.stderr)
        return None
    create_all(engine)
    return engine


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


def parse_values(text: str, cast: Callable[[str], Any]) -> list[Any]:
    """Parse a comma-separated list like ``20,40,80``; raise ``ValueError`` if invalid."""
    parts = [p.strip() for p in text.split(",")]
    try:
        values = [cast(p) for p in parts]
    except ValueError:
        raise ValueError(f"invalid value list: {text!r}") from None
    if not values:
        raise ValueError(f"invalid value list: {text!r}")
    return values


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


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
    tu = sub.add_parser("tune", help="grid search over K, LAMBDA and MIN_OVERLAP")
    tu.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="where MovieLens is stored or downloaded to (default: %(default)s)",
    )
    tu.add_argument(
        "--k", default="20,40,80", help="comma-separated K values (default: %(default)s)"
    )
    tu.add_argument(
        "--lambda",
        dest="lam",
        default="2,5,10",
        help="comma-separated LAMBDA values (default: %(default)s)",
    )
    tu.add_argument(
        "--min-overlap",
        default="3,5,8",
        help="comma-separated MIN_OVERLAP values (default: %(default)s)",
    )
    tu.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="recommendations per user, also the cut-off for precision/recall "
        "(default: %(default)s)",
    )
    tu.add_argument(
        "--seed", type=int, default=0, help="train/test split seed (default: %(default)s)"
    )
    imp = sub.add_parser("import-movielens", help="import MovieLens into the database")
    imp.add_argument(
        "--database-url",
        default=None,
        help=_DATABASE_URL_HELP,
    )
    imp.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="where MovieLens is stored or downloaded to (default: %(default)s)",
    )
    en = sub.add_parser("enrich-movies", help="fetch movie metadata from TMDB into the database")
    en.add_argument(
        "--database-url",
        default=None,
        help=_DATABASE_URL_HELP,
    )
    en.add_argument(
        "--limit", type=_positive_int, default=None, help="maximum number of movies to enrich"
    )
    me = sub.add_parser("metrics", help="print product metrics from the event log")
    me.add_argument(
        "--database-url",
        default=None,
        help=_DATABASE_URL_HELP,
    )
    me.add_argument(
        "--since",
        type=_iso_datetime,
        default=None,
        help="only count events at or after this ISO date/time, e.g. 2026-10-01 "
        "(UTC if no zone); affects good session rates, not retention",
    )
    sv = sub.add_parser("serve", help="run the web API")
    sv.add_argument("--host", default="127.0.0.1", help="bind address (default: %(default)s)")
    sv.add_argument("--port", type=int, default=8000, help="bind port (default: %(default)s)")
    sv.add_argument("--database-url", default=None, help=_DATABASE_URL_HELP)
    return parser


def _iso_datetime(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid ISO date/time: {text!r}") from None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _run_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from cinemate.api.app import create_app

    try:
        app = create_app(args.database_url)
    except (ArgumentError, ImportError):
        print("cinemate serve: error: invalid database URL", file=sys.stderr)
        return 2
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _run_metrics(args: argparse.Namespace) -> int:
    engine = _open_engine(args)
    if engine is None:
        return 2
    with Session(engine) as session:
        overall = good_session_rate(session, args.since)
        by_strategy = good_session_rate_by_strategy(session, args.since)
        retention = retention_7d(session)
    print(f"good session rate: {overall.rate:.4f} ({overall.good}/{overall.total} sessions)")
    for strategy, rate in by_strategy.items():
        print(f"  {strategy}: {rate.rate:.4f} ({rate.good}/{rate.total})")
    print(f"7-day retention: {retention:.4f}")
    return 0


def _run_enrich(args: argparse.Namespace) -> int:
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        print("cinemate enrich-movies: error: TMDB_API_KEY is not set", file=sys.stderr)
        return 2
    engine = _open_engine(args)
    if engine is None:
        return 2
    with Session(engine) as session:
        try:
            stats = enrich_movies(session, TmdbClient(api_key), limit=args.limit)
        except TmdbError as exc:
            print(f"cinemate enrich-movies: error: {exc}", file=sys.stderr)
            return 1
    print(f"movies enriched: {stats.enriched}, not found: {stats.not_found}")
    return 0


def _run_import(args: argparse.Namespace) -> int:
    dataset = ensure_movielens(args.data_dir)
    engine = _open_engine(args)
    if engine is None:
        return 2
    with Session(engine) as session:
        stats = import_movielens(session, dataset, MovieLensBinarizer())
    print(
        f"movies added: {stats.movies_added}, users added: {stats.users_added}, "
        f"ratings added: {stats.ratings_added}, ratings skipped: {stats.ratings_skipped}, "
        f"popularity updated: {stats.popularity_updated}"
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


def _run_tune(args: argparse.Namespace) -> int:
    try:
        grid = {
            "k": parse_values(args.k, int),
            "lam": parse_values(args.lam, float),
            "min_overlap": parse_values(args.min_overlap, int),
        }
    except ValueError as exc:
        print(f"cinemate tune: error: {exc}", file=sys.stderr)
        return 2
    dataset = ensure_movielens(args.data_dir)
    ratings = list(parse_ratings(dataset / "ratings.csv"))
    train, test = split_ratings(ratings, seed=args.seed)
    result = tune(train, test, MovieLensBinarizer(), grid, top_n=args.top_n)
    print(format_tune_table(result, args.top_n))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "evaluate":
        return _run_evaluate(args)
    if args.command == "tune":
        return _run_tune(args)
    if args.command == "import-movielens":
        return _run_import(args)
    if args.command == "metrics":
        return _run_metrics(args)
    if args.command == "enrich-movies":
        return _run_enrich(args)
    if args.command == "serve":
        return _run_serve(args)
    return 0
