# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

CineMate is at an early stage: the `cinemate` package has `__version__` and a minimal CLI (`cinemate/cli.py`, entry point `cinemate`, also `python -m cinemate`) that supports `--version`. `tests/` has a smoke test and CLI tests. `cinemate/movielens.py` has parsers for MovieLens CSV files (movies, ratings, links) with tests in `tests/test_movielens.py`. `cinemate/recommender/matrix.py` builds the sparse +1/-1 user x movie matrix (`build_matrix`), tests in `tests/test_matrix.py`. `cinemate/recommender/similarity.py` has `find_neighbors` (cosine top-K neighbours with a `min_overlap` threshold), tests in `tests/test_similarity.py`.  `cinemate/recommender/scoring.py` has `recommend` (neighbour scoring with shrinkage and popularity penalty), tests in `tests/test_scoring.py`. There is no other application code yet — update this file as it appears.

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
