import pytest

from cinemate.binarize import MovieLensBinarizer
from cinemate.cli import main, parse_values
from cinemate.evaluation.runner import MethodMetrics
from cinemate.evaluation.tune import TuneResult, TuneRow, format_tune_table, tune
from cinemate.movielens import Rating

B = MovieLensBinarizer()


def likes(user: int, *movies: int) -> list[Rating]:
    return [Rating(user, m, 5.0) for m in movies]


def make_train() -> list[Rating]:
    train = likes(1, 1, 2, 3, 4, 5) + likes(2, 1, 2, 3, 4, 5, 6, 7) + likes(3, 8, 9, 10)
    train += [Rating(4, m, 1.0) for m in (6, 7, 8, 9, 10)]
    return train


GRID = {"k": [1, 5], "lam": [1.0, 5.0], "min_overlap": [1, 3]}


def test_tune_row_count_and_sorting():
    result = tune(make_train(), likes(1, 6, 7), B, GRID, top_n=2)
    assert len(result.rows) == 8
    assert len({(r.k, r.lam, r.min_overlap) for r in result.rows}) == 8
    precisions = [r.metrics.precision_at_k for r in result.rows]
    assert precisions == sorted(precisions, reverse=True)
    assert result.n_users == 1
    assert result.baseline.precision_at_k == 0.0


def test_tune_empty_grid_and_missing_keys():
    result = tune(make_train(), likes(1, 6), B, {**GRID, "k": []})
    assert result.rows == []
    with pytest.raises(ValueError, match="min_overlap"):
        tune(make_train(), likes(1, 6), B, {"k": [1], "lam": [1.0]})


def test_format_tune_table():
    m = MethodMetrics(0.5, 0.25, 0.1, 0.2)
    rows = [TuneRow(40, 5.0, 5, m), TuneRow(20, 2.5, 3, MethodMetrics(0.1, 0.1, 0.1, 0.1))]
    out = format_tune_table(TuneResult(rows, MethodMetrics(0.05, 0.02, 0.01, 0.9), 7), 10)
    lines = out.splitlines()
    assert "precision@10" in lines[0] and "min_overlap" in lines[0]
    assert lines[1].split()[:3] == ["40", "5", "5"]
    assert lines[2].split()[:3] == ["20", "2.5", "3"]
    assert lines[3].split()[0] == "popular" and "0.0500" in lines[3]
    assert lines[-1] == "users evaluated: 7"


def test_parse_values():
    assert parse_values("20, 40,80", int) == [20, 40, 80]
    assert parse_values("2,5.5", float) == [2.0, 5.5]
    for bad in ("20,abc", "", "1,,2"):
        with pytest.raises(ValueError, match="invalid value list"):
            parse_values(bad, int)


def test_tune_command_offline(monkeypatch, tmp_path, capsys):
    import cinemate.cli as cli

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    code = main(["tune", "--k", "3,5", "--lambda", "1", "--min-overlap", "1", "--top-n", "3"])
    out = capsys.readouterr().out
    assert code == 0
    assert "popular" in out and "precision@3" in out
    assert len(out.splitlines()) == 1 + 2 + 1 + 2


def test_tune_command_rejects_bad_list(capsys):
    assert main(["tune", "--k", "20,abc"]) != 0
    assert "invalid value list" in capsys.readouterr().err
