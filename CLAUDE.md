# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

CineMate is at an early stage: the `cinemate` package contains only `__version__`, and `tests/` has a single smoke test. There is no application code or architecture yet — update this file as it appears.

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
