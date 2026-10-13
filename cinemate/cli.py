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
from cinemate.config import RecommenderSettings
from cinemate.datasets import DEFAULT_DATA_DIR, ensure_movielens
from cinemate.db.enrich import enrich_movies
from cinemate.db.importer import import_movielens
from cinemate.db.session import create_all, make_engine
from cinemate.evaluation.metrics import split_ratings
from cinemate.evaluation.runner import (
    EvaluationResult,
    MethodMetrics,
    Split,
    evaluate_seeds,
    format_metric_cells,
    new_users_line,
    parse_seeds,
)
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
    """Render ``result`` as a text table: one row per method (CF and baselines), then users."""
    headers = [
        f"precision@{top_n}",
        f"recall@{top_n}",
        f"hit_rate@{top_n}",
        "coverage",
        "mean popularity",
    ]
    rows = [("collaborative", result.cf), *result.baselines.items()]

    multi = len(result.seeds) > 1

    def cells(m: MethodMetrics) -> list[str]:
        return format_metric_cells(m, multi)

    name_width = max(len(name) for name, _ in rows)
    widths = [max(len(h), *(len(cells(m)[i]) for _, m in rows)) for i, h in enumerate(headers)]
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
    lines.append(f"seeds: {','.join(map(str, result.seeds))}")
    if result.new_user_ratings is not None:
        lines.append(
            new_users_line(result.new_user_ratings, result.new_user_pick, result.new_user_seen)
        )
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
    ev.add_argument(
        "--k",
        type=int,
        default=RecommenderSettings().k,
        help="number of neighbours (default: %(default)s)",
    )
    ev.add_argument(
        "--lambda",
        dest="lam",
        type=float,
        default=RecommenderSettings().lam,
        help="shrinkage strength (default: %(default)s)",
    )
    ev.add_argument(
        "--min-overlap",
        type=int,
        default=RecommenderSettings().min_overlap,
        help="minimum co-rated movies for a neighbour (default: %(default)s)",
    )
    ev.add_argument(
        "--pop-penalty",
        type=float,
        default=RecommenderSettings().pop_penalty,
        help="popularity penalty exponent, 0 disables it (default: %(default)s)",
    )
    ev.add_argument(
        "--significance",
        type=int,
        default=RecommenderSettings().significance,
        help="significance weighting threshold, 0 disables it (default: %(default)s)",
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
    ev.add_argument(
        "--seeds",
        default=None,
        help="comma-separated split seeds, metrics are averaged (mean±std in tables); "
        "default: --seed",
    )
    ev.add_argument(
        "--new-user-ratings",
        type=int,
        default=None,
        help="cold start: evaluate only 'new' users (half of them) keeping N train ratings each",
    )
    ev.add_argument(
        "--new-user-pick",
        choices=["random", "onboarding"],
        default="random",
        help="with --new-user-ratings: which ratings a 'new' user keeps, random ones or the "
        "first ones in onboarding card order (default: %(default)s)",
    )
    ev.add_argument(
        "--new-user-seen",
        choices=["all", "kept"],
        default="all",
        help="with --new-user-ratings: exclude from the lists all train ratings of a 'new' user "
        "or only the ones kept in the matrix, as the site does (default: %(default)s)",
    )
    tu = sub.add_parser("tune", help="grid search over K, LAMBDA, MIN_OVERLAP and POP_PENALTY")
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
        default="1,2,3",
        help="comma-separated MIN_OVERLAP values (default: %(default)s)",
    )
    tu.add_argument(
        "--pop-penalty",
        default="1",
        help="comma-separated popularity penalty exponents, 0 disables it (default: %(default)s)",
    )
    tu.add_argument(
        "--significance",
        default=str(RecommenderSettings().significance),
        help="comma-separated significance weighting thresholds, 0 disables it "
        "(default: %(default)s)",
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
    tu.add_argument(
        "--seeds",
        default=None,
        help="comma-separated split seeds, metrics are averaged (mean±std in tables); "
        "default: --seed",
    )
    tu.add_argument(
        "--new-user-ratings",
        type=int,
        default=None,
        help="cold start: evaluate only 'new' users (half of them) keeping N train ratings each",
    )
    tu.add_argument(
        "--new-user-pick",
        choices=["random", "onboarding"],
        default="random",
        help="with --new-user-ratings: which ratings a 'new' user keeps, random ones or the "
        "first ones in onboarding card order (default: %(default)s)",
    )
    tu.add_argument(
        "--new-user-seen",
        choices=["all", "kept"],
        default="all",
        help="with --new-user-ratings: exclude from the lists all train ratings of a 'new' user "
        "or only the ones kept in the matrix, as the site does (default: %(default)s)",
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
    sv.add_argument(
        "--cookie-secure",
        action="store_true",
        help="set the Secure flag on the session cookie (use over HTTPS); "
        "otherwise env COOKIE_SECURE (1/true/yes/on), default off",
    )
    return parser


def _iso_datetime(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid ISO date/time: {text!r}") from None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _run_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from cinemate.api.app import create_app, resolve_cookie_secure

    try:
        cookie_secure = resolve_cookie_secure(args.cookie_secure)
    except ValueError as exc:
        print(f"cinemate serve: error: {exc}", file=sys.stderr)
        return 2
    try:
        app = create_app(args.database_url, cookie_secure=cookie_secure)
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


def _settings_from_env(command: str) -> RecommenderSettings | None:
    """Read ``REC_*`` from the environment; print an error and return ``None`` if invalid."""
    try:
        return RecommenderSettings.from_env()
    except ValueError as exc:
        print(f"cinemate {command}: error: {exc}", file=sys.stderr)
        return None


def _make_splits(args: argparse.Namespace, command: str, ratings: list) -> list[Split] | None:
    """Splits for ``--seeds`` (or the single ``--seed``); prints an error and returns ``None``."""
    try:
        seeds = parse_seeds(args.seeds) if args.seeds is not None else [args.seed]
    except ValueError as exc:
        print(f"cinemate {command}: error: {exc}", file=sys.stderr)
        return None
    splits = []
    for seed in seeds:
        train, test = split_ratings(ratings, seed=seed)
        splits.append(Split(seed, train, test))
    return splits


def _check_seeds(args: argparse.Namespace, command: str) -> bool:
    try:
        if args.seeds is not None:
            parse_seeds(args.seeds)
    except ValueError as exc:
        print(f"cinemate {command}: error: {exc}", file=sys.stderr)
        return False
    return True


def _run_evaluate(args: argparse.Namespace) -> int:
    if not args.pop_penalty >= 0:
        print("cinemate evaluate: error: --pop-penalty must be >= 0", file=sys.stderr)
        return 2
    if args.significance < 0:
        print("cinemate evaluate: error: --significance must be >= 0", file=sys.stderr)
        return 2
    if args.new_user_ratings is not None and args.new_user_ratings < 1:
        print("cinemate evaluate: error: --new-user-ratings must be >= 1", file=sys.stderr)
        return 2
    if args.new_user_pick != "random" and args.new_user_ratings is None:
        print(
            "cinemate evaluate: error: --new-user-pick requires --new-user-ratings", file=sys.stderr
        )
        return 2
    if args.new_user_seen != "all" and args.new_user_ratings is None:
        print(
            "cinemate evaluate: error: --new-user-seen requires --new-user-ratings", file=sys.stderr
        )
        return 2
    if not _check_seeds(args, "evaluate"):
        return 2
    settings = _settings_from_env("evaluate")
    if settings is None:
        return 2
    dataset = ensure_movielens(args.data_dir)
    ratings = list(parse_ratings(dataset / "ratings.csv"))
    splits = _make_splits(args, "evaluate", ratings)
    assert splits is not None
    result = evaluate_seeds(
        splits,
        MovieLensBinarizer(),
        k=args.k,
        lam=args.lam,
        min_overlap=args.min_overlap,
        top_n=args.top_n,
        pop_penalty=args.pop_penalty,
        significance=args.significance,
        new_user_ratings=args.new_user_ratings,
        settings=settings,
        new_user_pick=args.new_user_pick,
        new_user_seen=args.new_user_seen,
    )
    print(format_table(result, args.top_n))
    return 0


def _run_tune(args: argparse.Namespace) -> int:
    try:
        grid = {
            "k": parse_values(args.k, int),
            "lam": parse_values(args.lam, float),
            "min_overlap": parse_values(args.min_overlap, int),
            "pop_penalty": parse_values(args.pop_penalty, float),
            "significance": parse_values(args.significance, int),
        }
        if not all(v >= 0 for v in grid["pop_penalty"]):
            raise ValueError("pop_penalty values must be >= 0")
        if not all(v >= 0 for v in grid["significance"]):
            raise ValueError("significance values must be >= 0")
    except ValueError as exc:
        print(f"cinemate tune: error: {exc}", file=sys.stderr)
        return 2
    if args.new_user_ratings is not None and args.new_user_ratings < 1:
        print("cinemate tune: error: --new-user-ratings must be >= 1", file=sys.stderr)
        return 2
    if args.new_user_pick != "random" and args.new_user_ratings is None:
        print("cinemate tune: error: --new-user-pick requires --new-user-ratings", file=sys.stderr)
        return 2
    if args.new_user_seen != "all" and args.new_user_ratings is None:
        print("cinemate tune: error: --new-user-seen requires --new-user-ratings", file=sys.stderr)
        return 2
    if not _check_seeds(args, "tune"):
        return 2
    settings = _settings_from_env("tune")
    if settings is None:
        return 2
    dataset = ensure_movielens(args.data_dir)
    ratings = list(parse_ratings(dataset / "ratings.csv"))
    splits = _make_splits(args, "tune", ratings)
    assert splits is not None
    first, *rest = splits
    result = tune(
        first.train,
        first.test,
        MovieLensBinarizer(),
        grid,
        top_n=args.top_n,
        new_user_ratings=args.new_user_ratings,
        seed=first.seed,
        settings=settings,
        extra_splits=rest,
        new_user_pick=args.new_user_pick,
        new_user_seen=args.new_user_seen,
    )
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
