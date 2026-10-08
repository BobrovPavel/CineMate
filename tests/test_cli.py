import subprocess
import sys

import pytest

import cinemate
from cinemate.cli import main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"cinemate {cinemate.__version__}"


def test_no_args_succeeds():
    assert main([]) == 0


def test_module_entrypoint():
    result = subprocess.run(
        [sys.executable, "-m", "cinemate", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert cinemate.__version__ in result.stdout


def _result():
    from cinemate.evaluation.runner import EvaluationResult, MethodMetrics

    return EvaluationResult(
        cf=MethodMetrics(0.1234, 0.2, 0.3, 0.05),
        baseline=MethodMetrics(0.05, 0.1, 0.01, 0.4),
        n_users=42,
    )


def test_format_table_rows_and_values():
    from cinemate.cli import format_table

    lines = format_table(_result()).splitlines()
    assert "precision@10" in lines[0] and "mean popularity" in lines[0]
    assert lines[1].split() == ["collaborative", "0.1234", "0.2000", "0.3000", "0.0500"]
    assert lines[2].split() == ["popular", "0.0500", "0.1000", "0.0100", "0.4000"]
    assert lines[-1] == "users evaluated: 42"


def test_format_table_uses_top_n_in_headers():
    from cinemate.cli import format_table

    assert "precision@5" in format_table(_result(), top_n=5)


def test_evaluate_command_offline(monkeypatch, tmp_path, capsys):
    import cinemate.cli as cli
    from cinemate.movielens import Rating

    calls = {}

    def fake_ensure(dest):
        calls["dest"] = dest
        return tmp_path

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", fake_ensure)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))

    code = main(
        [
            "evaluate",
            "--data-dir",
            str(tmp_path),
            "--k",
            "5",
            "--lambda",
            "1",
            "--min-overlap",
            "1",
            "--top-n",
            "3",
            "--seed",
            "1",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert calls["dest"] == tmp_path
    assert "collaborative" in out and "popular" in out
    assert "users evaluated:" in out


def test_evaluate_help_lists_arguments(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["evaluate", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--data-dir", "--k", "--lambda", "--min-overlap", "--top-n", "--seed"):
        assert flag in out
