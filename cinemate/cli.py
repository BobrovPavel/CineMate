import argparse
import csv
import os
import sys
import urllib.error
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from cinemate import __version__
from cinemate.binarize import Binarizer, MovieLensBinarizer, RelativeMeanBinarizer
from cinemate.config import RecommenderSettings
from cinemate.datasets import (
    DATASET_DIR,
    DATASETS,
    DEFAULT_DATA_DIR,
    ChecksumError,
    ensure_movielens,
)
from cinemate.db.enrich import DEFAULT_STALE_DAYS, MAX_STALE_DAYS, enrich_movies
from cinemate.db.importer import import_movielens
from cinemate.db.migrations import (
    SchemaNotMigratedError,
    current_revision,
    has_tables,
    stamp_head,
    upgrade_head,
)
from cinemate.db.ratings_import import import_ratings_csv
from cinemate.db.session import create_all, make_engine
from cinemate.evaluation.metrics import split_ratings
from cinemate.evaluation.runner import (
    EvaluationResult,
    MethodMetrics,
    Split,
    established_users_line,
    evaluate_seeds,
    format_metric_cells,
    new_users_line,
    parse_seeds,
)
from cinemate.evaluation.summary import describe_ratings, format_summary
from cinemate.evaluation.tune import format_tune_table, tune
from cinemate.movielens import Rating, iter_ratings, parse_ratings
from cinemate.ratings_csv import CSV_MIN_RATINGS, load_ratings
from cinemate.services.metrics import good_session_rate, good_session_rate_by_strategy, retention_7d
from cinemate.tmdb import TmdbClient, TmdbError
from cinemate.wikidata import DEFAULT_PATH as WIKIDATA_PATH
from cinemate.wikidata import WikidataError, fetch_mapping, load_mapping, save_mapping

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
    extra = established_users_line(result.user_fraction, result.established_users)
    if extra:
        lines.append(extra)
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


def _stale_days(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {text!r}") from None
    if not 1 <= value <= MAX_STALE_DAYS:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_STALE_DAYS}")
    return value


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return value


def _add_dataset_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--dataset",
        choices=DATASETS,
        default=DATASET_DIR,
        help="MovieLens dataset to download and read (default: %(default)s)",
    )
    p.add_argument(
        "--min-user-ratings",
        type=_non_negative_int,
        default=0,
        help="keep only users with at least N ratings (default: %(default)s)",
    )
    p.add_argument(
        "--max-users",
        type=_positive_int,
        default=None,
        help="keep a random sample (by --seed) of at most N of the eligible users "
        "(default: no limit)",
    )


def _add_source_args(p: argparse.ArgumentParser) -> None:
    _add_dataset_args(p)
    p.add_argument(
        "--source",
        choices=["movielens", "csv"],
        default="movielens",
        help="ratings source: MovieLens (downloaded) or an external ratings CSV "
        "(default: %(default)s)",
    )
    p.add_argument(
        "--ratings-csv",
        type=Path,
        default=None,
        help="with --source csv: path to ratings.csv (user_id, kp_id/tmdb_id/imdb_id, user_rating)",
    )
    p.add_argument(
        "--types",
        default=None,
        help="with --source csv: comma-separated movie types to keep, e.g. Film,TvSeries "
        "(default: all)",
    )
    p.add_argument(
        "--rel-threshold",
        type=float,
        default=None,
        help="with --source csv: a rating at least this far above (below) the user's mean "
        "score is a like (dislike), 0.5 if unset. The mean is computed once per user over "
        "all ratings, test ones included, which biases the result slightly",
    )


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
    ev.add_argument(
        "--user-fraction",
        type=float,
        default=1.0,
        help="with --new-user-ratings: keep only this share (0 < F <= 1) of the established "
        "(neighbour) users, random by seed, to see how quality depends on the user base "
        "size (default: %(default)s)",
    )
    ev.add_argument(
        "--blend-full-at",
        default="10,30",
        help="comma-separated hybrid thresholds T (ratings at which the hybrid is fully CF); "
        "each adds a hybrid(T=...) row (default: %(default)s)",
    )
    ev.add_argument(
        "--item-min-overlap",
        type=int,
        default=3,
        help="item_based row: minimum common raters for a non-zero movie similarity "
        "(default: %(default)s)",
    )
    ev.add_argument(
        "--item-lambda",
        type=float,
        default=5.0,
        help="item_based row: shrinkage lambda (default: %(default)s)",
    )
    _add_source_args(ev)
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
    tu.add_argument(
        "--user-fraction",
        type=float,
        default=1.0,
        help="with --new-user-ratings: keep only this share (0 < F <= 1) of the established "
        "(neighbour) users, random by seed, to see how quality depends on the user base "
        "size (default: %(default)s)",
    )
    tu.add_argument(
        "--blend-full-at",
        default="10,30",
        help="comma-separated hybrid thresholds T (ratings at which the hybrid is fully CF); "
        "each adds a hybrid(T=...) row (default: %(default)s)",
    )
    _add_source_args(tu)
    imp = sub.add_parser("import-movielens", help="import MovieLens into the database")
    _add_dataset_args(imp)
    imp.add_argument(
        "--seed",
        type=int,
        default=0,
        help="seed of the --max-users sample (default: %(default)s)",
    )
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
    ir = sub.add_parser(
        "import-ratings-csv", help="import movies, users and ratings from a ratings CSV"
    )
    ir.add_argument("--database-url", default=None, help=_DATABASE_URL_HELP)
    ir.add_argument(
        "--file", type=Path, required=True, help="path to ratings.csv (user_rating on a 1-10 scale)"
    )
    ir.add_argument(
        "--types",
        default=None,
        help="comma-separated movie types to keep, e.g. Film,TvSeries (default: all)",
    )
    ir.add_argument(
        "--rel-threshold",
        type=float,
        default=0.5,
        help="a rating at least this far above (below) the user's mean score is a like "
        "(dislike) (default: %(default)s)",
    )
    ir.add_argument(
        "--no-tmdb",
        action="store_true",
        help="skip the TMDB /find and title search steps (TMDB_API_KEY is still used for "
        "rows with tmdb_id)",
    )
    ir.add_argument(
        "--wikidata",
        type=Path,
        default=None,
        help=f"Kinopoisk -> TMDB/IMDb mapping from fetch-wikidata-kinopoisk "
        f"(default: {WIKIDATA_PATH} if it exists)",
    )
    fw = sub.add_parser(
        "fetch-wikidata-kinopoisk",
        help="download the Kinopoisk -> TMDB/IMDb mapping from Wikidata into a CSV",
    )
    fw.add_argument(
        "--out", type=Path, default=WIKIDATA_PATH, help="output CSV (default: %(default)s)"
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
    en.add_argument(
        "--refresh-titles",
        action="store_true",
        help="only refresh movies that lack a Russian title, whatever their age",
    )
    en.add_argument(
        "--stale-days",
        type=_stale_days,
        default=DEFAULT_STALE_DAYS,
        help=f"refresh movies fetched from TMDB more than this many days ago (1..{MAX_STALE_DAYS},"
        f" default {DEFAULT_STALE_DAYS})",
    )
    be = sub.add_parser(
        "bench-recommendations",
        help="time the matrix load and get_recommendations on a database",
    )
    be.add_argument("--database-url", default=None, help=_DATABASE_URL_HELP)
    be.add_argument("--pool", choices=["ru", "world"], default="world", help="user pool")
    be.add_argument(
        "--requests", type=int, default=20, help="number of requests (default: %(default)s)"
    )
    be.add_argument("--seed", type=int, default=0, help="random seed (default: %(default)s)")
    be.add_argument(
        "--synthetic",
        type=int,
        default=None,
        metavar="N",
        help="first fill an EMPTY database with about N random ratings",
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
    mg = sub.add_parser("migrate", help="apply database migrations (alembic upgrade head)")
    mg.add_argument("--database-url", default=None, help=_DATABASE_URL_HELP)
    mg.add_argument(
        "--stamp-existing",
        action="store_true",
        help="mark an existing database created without migrations (create_all) as up to date "
        "without changing its tables",
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
    except SchemaNotMigratedError as exc:
        print(f"cinemate serve: error: {exc}", file=sys.stderr)
        return 2
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _run_migrate(args: argparse.Namespace) -> int:
    try:
        engine = make_engine(resolve_database_url(args.database_url))
    except (ArgumentError, ImportError):
        print("cinemate migrate: error: invalid database URL", file=sys.stderr)
        return 2
    if args.stamp_existing:
        if current_revision(engine) is not None:
            print(
                "cinemate migrate: error: the database is already under migration control; "
                "run `cinemate migrate` without --stamp-existing",
                file=sys.stderr,
            )
            return 2
        if not has_tables(engine):
            print(
                "cinemate migrate: error: the database has no tables to stamp; "
                "run `cinemate migrate` without --stamp-existing",
                file=sys.stderr,
            )
            return 2
        stamp_head(engine)
        print("stamped the existing database as up to date")
        return 0
    if current_revision(engine) is None and has_tables(engine):
        print(
            "cinemate migrate: error: the database was created without migrations; "
            "run `cinemate migrate --stamp-existing` first",
            file=sys.stderr,
        )
        return 2
    upgrade_head(engine)
    print("database schema is up to date")
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


def _run_bench(args: argparse.Namespace) -> int:
    from cinemate.bench import fill_synthetic, format_bench, run_bench

    if args.requests < 1:
        print("cinemate bench-recommendations: error: --requests must be >= 1", file=sys.stderr)
        return 2
    engine = _open_engine(args)
    if engine is None:
        return 2
    try:
        if args.synthetic is not None:
            count = fill_synthetic(engine, args.synthetic, args.pool, args.seed)
            print(f"inserted {count} synthetic ratings")
        print(format_bench(run_bench(engine, args.pool, args.requests, args.seed)))
    except ValueError as exc:
        print(f"cinemate bench-recommendations: error: {exc}", file=sys.stderr)
        return 2
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
            stats = enrich_movies(
                session,
                TmdbClient(api_key),
                limit=args.limit,
                refresh_titles=args.refresh_titles,
                stale_days=args.stale_days,
            )
        except TmdbError as exc:
            print(f"cinemate enrich-movies: error: {exc}", file=sys.stderr)
            return 1
    print(
        f"movies enriched: {stats.enriched}, not found: {stats.not_found}, "
        f"skipped (no TMDB pair): {stats.skipped}"
    )
    return 0


def _print_progress(read: int) -> None:
    print(f"ratings read: {read}", flush=True)


def _download_dataset(args: argparse.Namespace, command: str) -> Path | None:
    """The dataset directory; prints an error and returns ``None`` if the download fails."""
    try:
        return ensure_movielens(args.data_dir, args.dataset)
    except (ChecksumError, urllib.error.URLError) as exc:
        print(f"cinemate {command}: error: cannot get {args.dataset}: {exc}", file=sys.stderr)
        return None


def _run_import(args: argparse.Namespace) -> int:
    dataset = _download_dataset(args, "import-movielens")
    if dataset is None:
        return 2
    engine = _open_engine(args)
    if engine is None:
        return 2
    with Session(engine) as session:
        stats = import_movielens(
            session,
            dataset,
            MovieLensBinarizer(),
            min_user_ratings=args.min_user_ratings,
            max_users=args.max_users,
            seed=args.seed,
            progress=_print_progress,
        )
    print(
        f"movies added: {stats.movies_added}, movies merged: {stats.movies_merged}, "
        f"users added: {stats.users_added}, "
        f"ratings added: {stats.ratings_added}, ratings skipped: {stats.ratings_skipped}, "
        f"popularity updated: {stats.popularity_updated}"
    )
    return 0


def _run_fetch_wikidata(args: argparse.Namespace) -> int:
    command = args.command
    try:
        result = fetch_mapping(progress=lambda n: print(f"rows read: {n}", flush=True))
        save_mapping(args.out, result.entries)
    except WikidataError as exc:
        print(f"cinemate {command}: error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(
            f"cinemate {command}: error: cannot write {args.out}: {exc.strerror}", file=sys.stderr
        )
        return 2
    print(f"mapping rows written: {len(result.entries)}, ambiguous dropped: {result.dropped}")
    return 0


def _run_import_ratings_csv(args: argparse.Namespace) -> int:
    command = args.command
    if not args.rel_threshold > 0:
        print(f"cinemate {command}: error: --rel-threshold must be > 0", file=sys.stderr)
        return 2
    types = [t for t in args.types.split(",") if t.strip()] if args.types is not None else None
    try:
        ratings = load_ratings(args.file, types)
    except OSError as exc:
        print(
            f"cinemate {command}: error: cannot read {args.file}: {exc.strerror}", file=sys.stderr
        )
        return 2
    except ValueError as exc:
        print(f"cinemate {command}: error: {args.file}: {exc}", file=sys.stderr)
        return 2
    binarizer = RelativeMeanBinarizer.fit(
        ratings, min_ratings=CSV_MIN_RATINGS, threshold=args.rel_threshold
    )
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        print(
            f"cinemate {command}: warning: TMDB_API_KEY is not set, working as with --no-tmdb",
            file=sys.stderr,
        )
    client = TmdbClient(api_key) if api_key else None
    wikidata_path = args.wikidata if args.wikidata is not None else WIKIDATA_PATH
    wikidata = None
    if args.wikidata is not None or wikidata_path.exists():
        try:
            wikidata = load_mapping(wikidata_path)
        except (OSError, ValueError, csv.Error) as exc:
            reason = exc.strerror if isinstance(exc, OSError) else exc
            print(
                f"cinemate {command}: error: cannot read {wikidata_path}: {reason}",
                file=sys.stderr,
            )
            return 2
    engine = _open_engine(args)
    if engine is None:
        return 2
    with Session(engine) as session:
        try:
            stats = import_ratings_csv(
                session,
                args.file,
                binarizer,
                types,
                client=client,
                use_tmdb=client is not None and not args.no_tmdb,
                wikidata=wikidata,
            )
        except ValueError as exc:
            print(f"cinemate {command}: error: {args.file}: {exc}", file=sys.stderr)
            return 2
        except TmdbError as exc:
            print(f"cinemate {command}: error: {exc}", file=sys.stderr)
            return 1
    print(
        f"matched by TMDB pair: {stats.matched_by_tmdb}, by IMDb: {stats.matched_by_imdb}, "
        f"by Kinopoisk: {stats.matched_by_kinopoisk}, by Wikidata: {stats.matched_by_wikidata}, "
        f"merged by Wikidata: {stats.merged_by_wikidata}, by search: {stats.matched_by_search}, "
        f"unresolved: {stats.unresolved}, conflicts: {stats.conflicts}"
    )
    print(
        f"movies merged: {stats.movies_merged}, movies added: {stats.movies_added}, "
        f"movies ambiguous: {stats.movies_ambiguous}, "
        f"movies skipped (no title): {stats.movies_skipped_no_title}, "
        f"users added: {stats.users_added}, ratings added: {stats.ratings_added}, "
        f"ratings skipped: {stats.ratings_skipped}, "
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


def _parse_blend(args: argparse.Namespace, command: str) -> list[float] | None:
    """Parse ``--blend-full-at``; print an error and return ``None`` if invalid."""
    try:
        values = parse_values(args.blend_full_at, float)
        if not all(v > 0 for v in values):
            raise ValueError("--blend-full-at values must be > 0")
    except ValueError as exc:
        print(f"cinemate {command}: error: {exc}", file=sys.stderr)
        return None
    return values


def _check_seeds(args: argparse.Namespace, command: str) -> bool:
    try:
        if args.seeds is not None:
            parse_seeds(args.seeds)
    except ValueError as exc:
        print(f"cinemate {command}: error: {exc}", file=sys.stderr)
        return False
    return True


def _load_source(args: argparse.Namespace, command: str) -> tuple[list[Rating], Binarizer] | None:
    """Ratings and binarizer for ``--source``; prints an error and returns ``None`` if invalid."""
    if args.source == "movielens":
        for flag, value in (
            ("--ratings-csv", args.ratings_csv),
            ("--types", args.types),
            ("--rel-threshold", args.rel_threshold),
        ):
            if value is not None:
                print(f"cinemate {command}: error: {flag} requires --source csv", file=sys.stderr)
                return None
        dataset = _download_dataset(args, command)
        if dataset is None:
            return None
        path = dataset / "ratings.csv"
        if args.min_user_ratings <= 0 and args.max_users is None:
            return list(parse_ratings(path)), MovieLensBinarizer()
        selected = iter_ratings(
            path,
            min_user_ratings=args.min_user_ratings,
            max_users=args.max_users,
            seed=args.seed,
        )
        return list(selected), MovieLensBinarizer()
    for flag, used in (
        ("--dataset", args.dataset != DATASET_DIR),
        ("--min-user-ratings", args.min_user_ratings > 0),
        ("--max-users", args.max_users is not None),
    ):
        if used:
            print(f"cinemate {command}: error: {flag} requires --source movielens", file=sys.stderr)
            return None
    if args.ratings_csv is None:
        print(f"cinemate {command}: error: --source csv requires --ratings-csv", file=sys.stderr)
        return None
    threshold = 0.5 if args.rel_threshold is None else args.rel_threshold
    if not threshold > 0:
        print(f"cinemate {command}: error: --rel-threshold must be > 0", file=sys.stderr)
        return None
    types = [t for t in args.types.split(",") if t.strip()] if args.types is not None else None
    try:
        ratings = load_ratings(args.ratings_csv, types)
    except OSError as exc:
        print(
            f"cinemate {command}: error: cannot read {args.ratings_csv}: {exc.strerror}",
            file=sys.stderr,
        )
        return None
    except ValueError as exc:
        print(f"cinemate {command}: error: {args.ratings_csv}: {exc}", file=sys.stderr)
        return None
    binarizer = RelativeMeanBinarizer.fit(ratings, min_ratings=CSV_MIN_RATINGS, threshold=threshold)
    return ratings, binarizer


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
    if args.item_min_overlap < 1:
        print("cinemate evaluate: error: --item-min-overlap must be >= 1", file=sys.stderr)
        return 2
    if not args.item_lambda >= 0:
        print("cinemate evaluate: error: --item-lambda must be >= 0", file=sys.stderr)
        return 2
    if not 0 < args.user_fraction <= 1:
        print("cinemate evaluate: error: --user-fraction must be in (0, 1]", file=sys.stderr)
        return 2
    if args.user_fraction != 1.0 and args.new_user_ratings is None:
        print(
            "cinemate evaluate: error: --user-fraction requires --new-user-ratings",
            file=sys.stderr,
        )
        return 2
    if not _check_seeds(args, "evaluate"):
        return 2
    blend = _parse_blend(args, "evaluate")
    if blend is None:
        return 2
    settings = _settings_from_env("evaluate")
    if settings is None:
        return 2
    source = _load_source(args, "evaluate")
    if source is None:
        return 2
    ratings, binarizer = source
    splits = _make_splits(args, "evaluate", ratings)
    assert splits is not None
    result = evaluate_seeds(
        splits,
        binarizer,
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
        blend_full_at=blend,
        item_min_overlap=args.item_min_overlap,
        item_lam=args.item_lambda,
        user_fraction=args.user_fraction,
    )
    print(format_summary(describe_ratings(ratings, binarizer)))
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
    if not 0 < args.user_fraction <= 1:
        print("cinemate tune: error: --user-fraction must be in (0, 1]", file=sys.stderr)
        return 2
    if args.user_fraction != 1.0 and args.new_user_ratings is None:
        print("cinemate tune: error: --user-fraction requires --new-user-ratings", file=sys.stderr)
        return 2
    if not _check_seeds(args, "tune"):
        return 2
    blend = _parse_blend(args, "tune")
    if blend is None:
        return 2
    settings = _settings_from_env("tune")
    if settings is None:
        return 2
    source = _load_source(args, "tune")
    if source is None:
        return 2
    ratings, binarizer = source
    splits = _make_splits(args, "tune", ratings)
    assert splits is not None
    first, *rest = splits
    result = tune(
        first.train,
        first.test,
        binarizer,
        grid,
        top_n=args.top_n,
        new_user_ratings=args.new_user_ratings,
        seed=first.seed,
        settings=settings,
        extra_splits=rest,
        new_user_pick=args.new_user_pick,
        new_user_seen=args.new_user_seen,
        blend_full_at=blend,
        user_fraction=args.user_fraction,
    )
    print(format_summary(describe_ratings(ratings, binarizer)))
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
    if args.command == "import-ratings-csv":
        return _run_import_ratings_csv(args)
    if args.command == "fetch-wikidata-kinopoisk":
        return _run_fetch_wikidata(args)
    if args.command == "metrics":
        return _run_metrics(args)
    if args.command == "bench-recommendations":
        return _run_bench(args)
    if args.command == "enrich-movies":
        return _run_enrich(args)
    if args.command == "migrate":
        return _run_migrate(args)
    if args.command == "serve":
        return _run_serve(args)
    return 0
