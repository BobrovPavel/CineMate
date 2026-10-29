import statistics

import pytest

import cinemate.evaluation.runner as runner
from cinemate import cli
from cinemate.binarize import MovieLensBinarizer
from cinemate.cli import format_table, main
from cinemate.evaluation.metrics import split_ratings
from cinemate.evaluation.runner import (
    EvaluationResult,
    MethodMetrics,
    Split,
    aggregate_metrics,
    evaluate_seeds,
    parse_seeds,
)
from cinemate.evaluation.tune import TuneResult, TuneRow, format_tune_table, tune
from cinemate.movielens import Rating

B = MovieLensBinarizer()
RATINGS = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
KW = {"k": 3, "lam": 1.0, "min_overlap": 1, "top_n": 3}


def _splits(seeds):
    return [Split(s, *split_ratings(RATINGS, seed=s)) for s in seeds]


def test_aggregate_mean_and_sample_std():
    runs = [MethodMetrics(0.2, 0.1, 0.5, 0.3, 0.6), MethodMetrics(0.4, 0.3, 0.7, 0.5, 0.8)]
    agg = aggregate_metrics(runs)
    assert agg.precision_at_k == pytest.approx(0.3)
    assert agg.precision_std == pytest.approx(statistics.stdev([0.2, 0.4]))
    assert agg.precision_std == pytest.approx(0.2 / 2**0.5)
    assert agg.recall_at_k == pytest.approx(0.2)
    assert agg.hit_rate_at_k == pytest.approx(0.7)
    assert agg.coverage == pytest.approx(0.6) and agg.mean_popularity == pytest.approx(0.4)


def test_aggregate_single_run_has_zero_std():
    m = MethodMetrics(0.2, 0.1, 0.5, 0.3, 0.6)
    assert aggregate_metrics([m]) == m


def test_evaluate_seeds_single_seed_matches_evaluate():
    [split] = _splits([3])
    single = runner.evaluate(split.train, split.test, B, seed=3, **KW)
    agg = evaluate_seeds([split], B, **KW)
    assert agg.cf == single.cf and agg.baselines == single.baselines
    assert agg.n_users == single.n_users and agg.seeds == (3,)


def test_evaluate_seeds_runs_once_per_seed(monkeypatch):
    calls = []
    real = runner.evaluate

    def spy(*args, **kwargs):
        calls.append(kwargs["seed"])
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "evaluate", spy)
    result = evaluate_seeds(_splits([0, 1, 2]), B, **KW)
    assert calls == [0, 1, 2] and result.seeds == (0, 1, 2)


def test_evaluate_seeds_aggregates_manually():
    splits = _splits([0, 1])
    each = [runner.evaluate(s.train, s.test, B, seed=s.seed, **KW) for s in splits]
    agg = evaluate_seeds(splits, B, **KW)
    values = [r.cf.precision_at_k for r in each]
    assert agg.cf.precision_at_k == pytest.approx(statistics.fmean(values))
    assert agg.cf.precision_std == pytest.approx(statistics.stdev(values))
    assert agg.n_users == each[0].n_users


def test_evaluate_seeds_rejects_empty_and_duplicates():
    with pytest.raises(ValueError):
        evaluate_seeds([], B, **KW)
    with pytest.raises(ValueError):
        evaluate_seeds(_splits([1, 1]), B, **KW)


def test_parse_seeds():
    assert parse_seeds("0, 1,2") == [0, 1, 2]
    for bad in ("", "a", "1,,2", "1,1"):
        with pytest.raises(ValueError):
            parse_seeds(bad)


def test_tune_runs_evaluate_for_every_seed_and_combination(monkeypatch):
    calls = []
    real = runner.evaluate

    def spy(*args, **kwargs):
        calls.append(kwargs["seed"])
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "evaluate", spy)
    first, *rest = _splits([0, 1, 2])
    grid = {"k": [3, 5], "lam": [1.0], "min_overlap": [1]}
    result = tune(first.train, first.test, B, grid, top_n=3, seed=0, extra_splits=rest)
    assert sorted(calls) == [0, 0, 1, 1, 2, 2] and result.seeds == (0, 1, 2)
    precisions = [r.metrics.precision_at_k for r in result.rows]
    assert precisions == sorted(precisions, reverse=True)


def _result(seeds):
    m = MethodMetrics(0.1997, 0.2, 0.5, 0.3, 0.8, 0.0042, 0.01, 0.02)
    return m, EvaluationResult(m, {"popular": m}, 5, seeds=seeds)


def test_tables_show_mean_and_std_only_with_several_seeds():
    m, multi = _result((0, 1, 2))
    lines = format_table(multi).splitlines()
    assert lines[1].split() == ["collaborative", "0.1997±0.0042", "0.2000±0.0100",
                                "0.8000±0.0200", "0.5000", "0.3000", "0.0000±0.0000",
                                "0.0000±0.0000", "(n=0)"]  # fmt: skip
    assert lines[-1] == "seeds: 0,1,2"
    tuned = format_tune_table(TuneResult([TuneRow(3, 1.0, 1, m)], {"popular": m}, 5, seeds=(0, 1)))
    assert "0.1997±0.0042" in tuned and tuned.splitlines()[-1] == "seeds: 0,1"
    _, single = _result((0,))
    assert "±" not in format_table(single)


@pytest.mark.parametrize("command", ["evaluate", "tune"])
@pytest.mark.parametrize("value", ["", "a", "1,1", "1,,2"])
def test_seeds_option_rejects_bad_lists(command, value, capsys):
    assert main([command, "--seeds", value]) == 2
    assert "seed" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["evaluate", "tune"])
def test_commands_with_seeds(command, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest, name="ml-latest-small": tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(RATINGS))
    argv = [command, "--min-overlap", "1", "--top-n", "3", "--seeds", "0,1,2"]
    if command == "tune":
        argv += ["--k", "3", "--lambda", "1"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "±" in out and "seeds: 0,1,2" in out


@pytest.mark.parametrize("command", ["evaluate", "tune"])
def test_help_describes_seeds(command, capsys):
    with pytest.raises(SystemExit):
        main([command, "--help"])
    assert "--seeds" in capsys.readouterr().out


def test_aggregate_new_metrics_mean_std_and_judged_users():
    runs = [
        MethodMetrics(
            0.2, 0.1, 0.5, 0.3, 0.6, dislike_at_k=0.1, like_share_judged=0.8, judged_users=10
        ),
        MethodMetrics(
            0.4, 0.3, 0.7, 0.5, 0.8, dislike_at_k=0.3, like_share_judged=0.9, judged_users=20
        ),
    ]
    agg = aggregate_metrics(runs)
    assert agg.dislike_at_k == pytest.approx(0.2)
    assert agg.dislike_std == pytest.approx(statistics.stdev([0.1, 0.3]))
    assert agg.like_share_judged == pytest.approx(0.85)
    assert agg.like_share_std == pytest.approx(statistics.stdev([0.8, 0.9]))
    assert agg.judged_users == 15
