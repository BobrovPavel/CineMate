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
    assert set(result.baselines) == {
        "popular",
        "popular_likes",
        "popular_share_20",
        "popular_share_50",
        "product",
        "item_based",
    }


def test_tune_empty_grid_and_missing_keys():
    result = tune(make_train(), likes(1, 6), B, {**GRID, "k": []})
    assert result.rows == []
    with pytest.raises(ValueError, match="min_overlap"):
        tune(make_train(), likes(1, 6), B, {"k": [1], "lam": [1.0]})


def test_format_tune_table():
    m = MethodMetrics(0.5, 0.25, 0.1, 0.2, 0.8)
    rows = [TuneRow(40, 5.0, 5, m), TuneRow(20, 2.5, 3, MethodMetrics(0.1, 0.1, 0.1, 0.1))]
    baselines = {
        "popular": MethodMetrics(0.05, 0.02, 0.01, 0.9),
        "popular_likes": MethodMetrics(0.06, 0.02, 0.01, 0.9),
        "popular_share_20": MethodMetrics(0.07, 0.02, 0.01, 0.9),
        "popular_share_50": MethodMetrics(0.08, 0.02, 0.01, 0.9),
    }
    out = format_tune_table(TuneResult(rows, baselines, 7), 10)
    lines = out.splitlines()
    assert "precision@10" in lines[0] and "min_overlap" in lines[0]
    assert "hit_rate@10" in lines[0]
    headers = lines[0].split()
    assert headers.index("hit_rate@10") == headers.index("recall@10") + 1
    assert lines[1].split()[headers.index("hit_rate@10")] == "0.8000"
    assert lines[1].split()[:3] == ["40", "5", "5"]
    assert lines[2].split()[:3] == ["20", "2.5", "3"]
    assert lines[3].split()[0] == "popular" and "0.0500" in lines[3]
    assert [line.split()[0] for line in lines[4:7]] == [
        "popular_likes",
        "popular_share_20",
        "popular_share_50",
    ]
    assert lines[-2:] == ["users evaluated: 7", "seeds: 0"]


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
    assert (
        len(out.splitlines()) == 1 + 1 + 2 + 5 + 3 + 2 + 1
    )  # + dataset line, hybrid x2, item_based


def test_tune_command_rejects_bad_list(capsys):
    assert main(["tune", "--k", "20,abc"]) != 0
    assert "invalid value list" in capsys.readouterr().err


def test_tune_pop_penalty_dimension_multiplies_rows():
    grid = {**GRID, "pop_penalty": [0.0, 1.0, 2.0]}
    result = tune(make_train(), likes(1, 6, 7), B, grid, top_n=2)
    assert len(result.rows) == 24
    assert {r.pop_penalty for r in result.rows} == {0.0, 1.0, 2.0}


def test_format_tune_table_has_pop_penalty_column():
    m = MethodMetrics(0.5, 0.25, 0.1, 0.2)
    baselines = {"popular": MethodMetrics(0.05, 0.02, 0.01, 0.9)}
    out = format_tune_table(TuneResult([TuneRow(40, 5.0, 5, m, 1.5)], baselines, 7), 10)
    lines = out.splitlines()
    assert "pop_penalty" in lines[0]
    assert lines[1].split()[:4] == ["40", "5", "5", "1.5"]
    assert "signif" in lines[0]
    assert lines[1].split()[4] == "0"


def test_tune_significance_dimension_multiplies_rows():
    grid = {**GRID, "significance": [0, 3, 5]}
    result = tune(make_train(), likes(1, 6, 7), B, grid, top_n=2)
    assert len(result.rows) == 24
    assert {r.significance for r in result.rows} == {0, 3, 5}


def test_tune_command_significance(monkeypatch, tmp_path, capsys):
    import cinemate.cli as cli

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    argv = ["tune", "--k", "3", "--lambda", "1", "--min-overlap", "1", "--top-n", "3"]
    assert main([*argv, "--significance", "0,5"]) == 0
    out = capsys.readouterr().out
    assert "signif" in out
    assert (
        len(out.splitlines()) == 1 + 1 + 2 + 5 + 3 + 2 + 1
    )  # + dataset line, hybrid x2, item_based


def test_tune_command_rejects_negative_significance(capsys):
    assert main(["tune", "--significance", "-1"]) == 2
    assert "significance" in capsys.readouterr().err


def test_tune_command_pop_penalty(monkeypatch, tmp_path, capsys):
    import cinemate.cli as cli

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    argv = ["tune", "--k", "3", "--lambda", "1", "--min-overlap", "1", "--top-n", "3"]
    assert main([*argv, "--pop-penalty", "0,0.5,1"]) == 0
    out = capsys.readouterr().out
    assert "pop_penalty" in out
    assert len(out.splitlines()) == 1 + 1 + 3 + 5 + 3 + 2 + 1  # + hybrid rows, item_based


def test_tune_command_rejects_negative_pop_penalty(capsys):
    assert main(["tune", "--pop-penalty", "-1"]) == 2
    assert "pop_penalty" in capsys.readouterr().err


def test_tune_cold_start_passes_parameters_and_prints_line():
    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    train, test = ratings[:150], ratings[150:]
    grid = {"k": [3], "lam": [1.0], "min_overlap": [1]}
    result = tune(train, test, B, grid, top_n=3, new_user_ratings=4, seed=1)
    assert result.new_user_ratings == 4
    assert "new users: 4 ratings each" in format_tune_table(result, 3)
    assert "new users" not in format_tune_table(tune(train, test, B, grid, top_n=3), 3)


@pytest.mark.parametrize("command", ["tune", "evaluate"])
@pytest.mark.parametrize("value", ["0", "-3"])
def test_cold_start_option_rejects_non_positive(command, value, capsys):
    assert main([command, "--new-user-ratings", value]) == 2
    assert "--new-user-ratings must be >= 1" in capsys.readouterr().err


def test_evaluate_command_cold_start(monkeypatch, tmp_path, capsys):
    from cinemate import cli

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    argv = ["evaluate", "--min-overlap", "1", "--top-n", "3", "--new-user-ratings", "5"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "product" in out and "new users: 5 ratings each" in out


def test_tune_passes_new_user_pick_and_prints_it():
    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    train, test = ratings[:150], ratings[150:]
    grid = {"k": [3], "lam": [1.0], "min_overlap": [1]}
    result = tune(train, test, B, grid, top_n=3, new_user_ratings=4, new_user_pick="onboarding")
    assert result.new_user_pick == "onboarding"
    assert "new users: 4 ratings each (pick: onboarding)" in format_tune_table(result, 3)


@pytest.mark.parametrize("command", ["tune", "evaluate"])
def test_new_user_pick_requires_new_user_ratings(command, capsys):
    assert main([command, "--new-user-pick", "onboarding"]) == 2
    assert "--new-user-pick requires --new-user-ratings" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["tune", "evaluate"])
def test_commands_run_with_onboarding_pick(command, monkeypatch, tmp_path, capsys):
    from cinemate import cli

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    argv = [command, "--min-overlap", "1", "--top-n", "3", "--new-user-ratings", "5"]
    if command == "tune":
        argv += ["--k", "3", "--lambda", "1"]
    assert main([*argv, "--new-user-pick", "onboarding"]) == 0
    assert "new users: 5 ratings each (pick: onboarding)" in capsys.readouterr().out


def test_tune_passes_new_user_seen_and_prints_it():
    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    train, test = ratings[:150], ratings[150:]
    grid = {"k": [3], "lam": [1.0], "min_overlap": [1]}
    result = tune(
        train,
        test,
        B,
        grid,
        top_n=3,
        new_user_ratings=4,
        new_user_pick="onboarding",
        new_user_seen="kept",
    )
    assert result.new_user_seen == "kept"
    assert "new users: 4 ratings each (pick: onboarding, seen: kept)" in format_tune_table(
        result, 3
    )


@pytest.mark.parametrize("command", ["tune", "evaluate"])
def test_new_user_seen_requires_new_user_ratings(command, capsys):
    assert main([command, "--new-user-seen", "kept"]) == 2
    assert "--new-user-seen requires --new-user-ratings" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["tune", "evaluate"])
def test_commands_run_with_seen_kept(command, monkeypatch, tmp_path, capsys):
    from cinemate import cli

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    argv = [command, "--min-overlap", "1", "--top-n", "3", "--new-user-ratings", "5"]
    if command == "tune":
        argv += ["--k", "3", "--lambda", "1"]
    assert main([*argv, "--new-user-pick", "onboarding", "--new-user-seen", "kept"]) == 0
    assert "new users: 5 ratings each (pick: onboarding, seen: kept)" in capsys.readouterr().out


def test_tune_user_fraction_reported_in_table():
    train = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    test = [Rating(u, 10, 5.0) for u in range(1, 21)]
    grid = {"k": [3], "lam": [1.0], "min_overlap": [1]}
    kw = {"top_n": 3, "new_user_ratings": 5}
    result = tune(train, test, B, grid, user_fraction=0.5, **kw)
    assert result.user_fraction == 0.5
    assert result.established_users is not None
    assert "established users: 5 of 10 (fraction 0.5)" in format_tune_table(result, 3)
    assert "established users" not in format_tune_table(tune(train, test, B, grid, **kw), 3)


@pytest.mark.parametrize("command", ["tune", "evaluate"])
def test_user_fraction_requires_new_user_ratings_cli(command, capsys):
    assert main([command, "--user-fraction", "0.5"]) == 2
    assert "--user-fraction requires --new-user-ratings" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["tune", "evaluate"])
@pytest.mark.parametrize("value", ["0", "1.5"])
def test_user_fraction_range_cli(command, value, capsys):
    assert main([command, "--user-fraction", value, "--new-user-ratings", "5"]) == 2
    assert "--user-fraction must be in (0, 1]" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["tune", "evaluate"])
def test_commands_run_with_user_fraction(command, monkeypatch, tmp_path, capsys):
    from cinemate import cli

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    argv = [command, "--min-overlap", "1", "--top-n", "3", "--new-user-ratings", "5"]
    if command == "tune":
        argv += ["--k", "3", "--lambda", "1"]
    assert main([*argv, "--new-user-pick", "onboarding", "--user-fraction", "0.5"]) == 0
    assert "established users:" in capsys.readouterr().out
