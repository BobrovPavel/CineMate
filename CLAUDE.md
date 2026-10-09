# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

CineMate is at an early stage: the `cinemate` package has `__version__` and a CLI (`cinemate/cli.py`, entry point `cinemate`, also `python -m cinemate`) with `--version` and the `evaluate` subcommand (downloads MovieLens, prints a CF vs popular metrics table via `format_table`). `tests/` has a smoke test and CLI tests. `cinemate/movielens.py` has parsers for MovieLens CSV files (movies, ratings, links) with tests in `tests/test_movielens.py`. `cinemate/recommender/matrix.py` builds the sparse +1/-1 user x movie matrix (`build_matrix`), tests in `tests/test_matrix.py`. `cinemate/recommender/similarity.py` has `find_neighbors` (cosine top-K neighbours with a `min_overlap` threshold), tests in `tests/test_similarity.py`. `cinemate/recommender/scoring.py` has `recommend` (neighbour scoring with shrinkage and popularity penalty), tests in `tests/test_scoring.py`. `cinemate/recommender/fallback.py` has `popular` (well-liked popular movies, random pick from a top pool) and `cinemate/recommender/strategy.py` has `recommend_with_strategy` returning a `Recommendation` (`items`, `strategy` = `collaborative` or `fallback`), tests in `tests/test_fallback.py`. `cinemate/datasets.py` has `ensure_movielens` (idempotent download and safe unzip of ml-latest-small into `data/`, which is gitignored), tests in `tests/test_datasets.py`. `cinemate/recommender/explain.py` has `explain` returning an `Explanation` (`liked_by`, `because_of` indices), tests in `tests/test_explain.py`. `cinemate/evaluation/metrics.py` has `split_ratings` (per-user train/test split), `precision_at_k`, `recall_at_k`, `coverage`, `mean_popularity`, tests in `tests/test_metrics.py`. `cinemate/evaluation/runner.py` has `evaluate` (user-based CF vs deterministic popular baseline on a train/test split, returns `EvaluationResult`) and `popular_baseline`, tests in `tests/test_runner.py`. `cinemate/db/` has SQLAlchemy 2.0 models (`Movie`, `User`, `Rating`, `SeenMark` in `models.py`) and `make_engine`/`create_all` (`session.py`), tests in `tests/test_db.py`. `cinemate/db/importer.py` has `import_movielens` (idempotent import of movies/users/ratings into the DB, returns `ImportStats`; users are matched via `User.external_movielens_id`; also recomputes `Movie.popularity_score` as the like count) and is exposed as the `cinemate import-movielens` subcommand, tests in `tests/test_importer.py`. `cinemate/evaluation/tune.py` has `tune` (grid search over `k`, `lam`, `min_overlap` via `evaluate`, returns `TuneResult` sorted by precision) and `format_tune_table`, exposed as the `cinemate tune` subcommand, tests in `tests/test_tune.py`. `cinemate/db/matrix_store.py` has `MatrixStore` (thread-safe in-memory cache of the ratings matrix loaded from the DB; `get()`/`invalidate()`), and `matrix_from_values` in `recommender/matrix.py` builds the matrix from binarized triples, tests in `tests/test_matrix_store.py`. `cinemate/tmdb.py` has `TmdbClient` (injectable `http_get`, `fetch_movie` returns `TmdbMovie` or `None` on 404, `TmdbError` otherwise, key never in messages), tests in `tests/test_tmdb.py`. `cinemate/db/enrich.py` has `enrich_movies` (fills `overview`/`poster_path`/`runtime` for movies with `tmdb_id` and no overview, returns `EnrichStats`) and is exposed as `cinemate enrich-movies` (key from env `TMDB_API_KEY`), tests in `tests/test_enrich.py`. `cinemate/services/users.py` has the framework-independent user service (`create_session_user`, `get_user_by_token`, `set_rating`, `set_seen_mark`, `get_ratings`; flush only, caller commits), tests in `tests/test_users_service.py`. `cinemate/services/recommendations.py` has `get_recommendations` (DB user -> `RecommendationsResult` with `strategy` and `RecommendedMovie` items carrying `liked_by`/`because_of`; excludes `watched`/`not_interested` marks), tests in `tests/test_recommendations_service.py`. `cinemate/services/metrics.py` has `good_session_rate`, `good_session_rate_by_strategy` and `retention_7d` (product metrics from the `Event` log), exposed as `cinemate metrics`, tests in `tests/test_metrics_service.py`. `cinemate/cli.py` has `resolve_database_url` (DB URL for `import-movielens`, `enrich-movies`, `metrics`: `--database-url` → env `DATABASE_URL` → `sqlite:///cinemate.db`), tests in `tests/test_cli.py`. `Dockerfile`, `docker-compose.yml` (PostgreSQL `db` + CLI `app`, password from `POSTGRES_PASSWORD`) and the `postgres` extra (`psycopg[binary]`) run the CLI commands in a container; the image was not built in the agent environment. `cinemate/api/` is the thin FastAPI layer: `create_app(database_url)` in `app.py` (engine, `create_all` and one `MatrixStore` kept in `app.state`), `get_db_session` (commit on success, rollback on exception) and `get_matrix_store` in `deps.py`, `GET /api/health`, `POST /api/session` (anonymous user + `cinemate_session` cookie, `cookie_secure` option of `create_app`), `GET /api/profile`, `GET /api/onboarding`, `POST /api/ratings` and `POST /api/seen` (writes return `{ok, rated_count}`; a reaction event is logged only when `session_id` is given) in `routes.py` (Pydantic models in `schemas.py`, `get_current_user` in `deps.py` → 401 without a valid cookie); exposed as `cinemate serve --host --port --database-url`, tests in `tests/test_api.py` and `tests/test_api_ratings.py`. `make_engine` uses a `StaticPool` for in-memory SQLite so it works across threads. There is no other application code yet — update this file as it appears.

## Setup

Python 3.12+. All tooling config lives in `pyproject.toml`; dev dependencies are the `dev` extra.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; source .venv/bin/activate elsewhere
pip install -e ".[dev]"
```

In cloud sessions: if `pytest` or `ruff` is not found, run `pip install -e ".[dev]"` first.

## Commands

```
ruff check .                    # lint (add --fix to autofix)
ruff format .                   # format; CI runs `ruff format --check .`
pytest                          # all tests (testpaths = tests)
pytest tests/test_smoke.py::test_package_imports   # single test
pytest --cov=cinemate --cov-report=term-missing    # what CI runs
```

## CI

`.github/workflows/ci.yml` runs on push to `main` and on PRs, as two parallel jobs on Python 3.12:
- `lint` — `ruff check .` and `ruff format --check .`
- `test` — pytest with coverage

Both must pass, so run `ruff check . && ruff format --check . && pytest` before pushing.

## Conventions

- Ruff: line length 100, target py312, rule sets `E, W, F, I, B, UP, SIM` (import order is enforced by `I`).
- pytest runs with `--strict-markers`: register custom markers in `[tool.pytest.ini_options]` before using them.
- New packages must match `cinemate*` to be picked up by setuptools package discovery.

## Agent workflow

- For tasks from an issue, work in branch `claude/issue-<N>` created from main; for ad-hoc sessions, the session-provided `claude/` branch is fine. Never push to main.
- Before opening a PR, `ruff check . && ruff format --check . && pytest` must pass.
- New logic must be covered by tests.
- PR description: `Closes #<N>`, what changed, how to verify.
- If a task is unclear, ask questions in an issue comment instead of guessing.
- Do not modify `.github/workflows/` unless the issue explicitly asks for it.
