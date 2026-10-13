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
        cf=MethodMetrics(0.1234, 0.2, 0.3, 0.05, 0.9),
        baselines={
            "popular": MethodMetrics(0.05, 0.1, 0.01, 0.4),
            "popular_likes": MethodMetrics(0.06, 0.1, 0.02, 0.5),
            "popular_share_20": MethodMetrics(0.07, 0.1, 0.03, 0.6),
            "popular_share_50": MethodMetrics(0.08, 0.1, 0.04, 0.7),
        },
        n_users=42,
    )


def test_format_table_rows_and_values():
    from cinemate.cli import format_table

    lines = format_table(_result()).splitlines()
    assert "precision@10" in lines[0] and "mean popularity" in lines[0]
    assert "hit_rate@10" in lines[0]
    headers = lines[0].split()
    assert headers.index("hit_rate@10") == headers.index("recall@10") + 1
    assert lines[1].split() == ["collaborative", "0.1234", "0.2000", "0.9000", "0.3000", "0.0500"]
    assert lines[2].split() == ["popular", "0.0500", "0.1000", "0.0000", "0.0100", "0.4000"]
    assert [line.split()[0] for line in lines[3:6]] == [
        "popular_likes",
        "popular_share_20",
        "popular_share_50",
    ]
    assert lines[-2:] == ["users evaluated: 42", "seeds: 0"]


def test_format_table_uses_top_n_in_headers():
    from cinemate.cli import format_table

    assert "precision@5" in format_table(_result(), top_n=5)
    assert "hit_rate@5" in format_table(_result(), top_n=5)


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


def test_evaluate_defaults_come_from_recommender_settings():
    from cinemate.cli import build_parser
    from cinemate.config import RecommenderSettings

    args = build_parser().parse_args(["evaluate"])
    settings = RecommenderSettings()
    assert (args.k, args.lam, args.min_overlap, args.pop_penalty) == (
        settings.k,
        settings.lam,
        settings.min_overlap,
        settings.pop_penalty,
    )
    assert (args.k, args.pop_penalty) == (60, 0.75)


def test_evaluate_help_lists_arguments(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["evaluate", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--data-dir", "--k", "--lambda", "--min-overlap", "--top-n", "--seed"):
        assert flag in out


def test_resolve_database_url_priority(monkeypatch):
    from cinemate.cli import DEFAULT_DATABASE_URL, resolve_database_url

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert resolve_database_url(None) == DEFAULT_DATABASE_URL
    monkeypatch.setenv("DATABASE_URL", "sqlite:///env.db")
    assert resolve_database_url(None) == "sqlite:///env.db"
    assert resolve_database_url("sqlite:///arg.db") == "sqlite:///arg.db"


def test_metrics_uses_database_url_env(monkeypatch, tmp_path, capsys):
    db = tmp_path / "env.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    assert main(["metrics"]) == 0
    assert db.exists()
    assert "good session rate" in capsys.readouterr().out


def test_metrics_argument_beats_env(monkeypatch, tmp_path):
    env_db, arg_db = tmp_path / "env.db", tmp_path / "arg.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{env_db}")
    assert main(["metrics", "--database-url", f"sqlite:///{arg_db}"]) == 0
    assert arg_db.exists()
    assert not env_db.exists()


def test_invalid_database_url_does_not_leak_password(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "not a url://user:s3cret@host/db")
    assert main(["metrics"]) == 2
    captured = capsys.readouterr()
    assert "s3cret" not in captured.out + captured.err
    assert "invalid database URL" in captured.err


def test_help_mentions_database_url_env(capsys):
    with pytest.raises(SystemExit):
        main(["metrics", "--help"])
    assert "DATABASE_URL" in capsys.readouterr().out


def test_serve_help_lists_arguments(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["serve", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--host" in out and "--port" in out and "--database-url" in out


def test_serve_runs_uvicorn(monkeypatch):
    import uvicorn

    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.update(app=app, **kw))
    code = main(["serve", "--database-url", "sqlite:///:memory:", "--port", "9000"])
    assert code == 0
    assert calls["host"] == "127.0.0.1" and calls["port"] == 9000
    assert calls["app"].title == "CineMate"


def test_serve_help_describes_cookie_secure(capsys):
    with pytest.raises(SystemExit):
        main(["serve", "--help"])
    out = capsys.readouterr().out
    assert "--cookie-secure" in out and "COOKIE_SECURE" in out


def _capture_serve(monkeypatch):
    import uvicorn

    import cinemate.api.app as app_module

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)

    def fake_create_app(database_url=None, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(app_module, "create_app", fake_create_app)
    return seen


def test_serve_passes_cookie_secure_flag(monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    seen = _capture_serve(monkeypatch)
    assert main(["serve", "--cookie-secure"]) == 0
    assert seen["cookie_secure"] is True


def test_serve_cookie_secure_default_off(monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    seen = _capture_serve(monkeypatch)
    assert main(["serve"]) == 0
    assert seen["cookie_secure"] is False


def test_serve_cookie_secure_from_env(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "on")
    seen = _capture_serve(monkeypatch)
    assert main(["serve"]) == 0
    assert seen["cookie_secure"] is True


def test_serve_invalid_cookie_secure_env(monkeypatch, capsys):
    monkeypatch.setenv("COOKIE_SECURE", "maybe")
    assert main(["serve", "--database-url", "sqlite:///:memory:"]) == 2
    assert "COOKIE_SECURE" in capsys.readouterr().err


def test_serve_invalid_database_url(capsys):
    assert main(["serve", "--database-url", "not a url"]) == 2
    assert "invalid database URL" in capsys.readouterr().err


def test_evaluate_command_pop_penalty(monkeypatch, tmp_path, capsys):
    import cinemate.cli as cli
    from cinemate.movielens import Rating

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    import cinemate.evaluation.runner as runner

    seen = {}
    real = runner.evaluate

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "evaluate", spy)
    argv = ["evaluate", "--min-overlap", "1", "--top-n", "3"]
    assert main([*argv, "--pop-penalty", "0.5"]) == 0
    assert seen["pop_penalty"] == 0.5
    capsys.readouterr()
    assert main([*argv, "--pop-penalty", "-1"]) == 2
    assert "pop-penalty" in capsys.readouterr().err


def test_evaluate_command_significance(monkeypatch, tmp_path, capsys):
    import cinemate.cli as cli
    from cinemate.movielens import Rating

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    import cinemate.evaluation.runner as runner

    seen = {}
    real = runner.evaluate

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "evaluate", spy)
    argv = ["evaluate", "--min-overlap", "1", "--top-n", "3"]
    assert main(argv) == 0
    assert seen["significance"] == 0
    assert main([*argv, "--significance", "5"]) == 0
    assert seen["significance"] == 5
    capsys.readouterr()
    assert main([*argv, "--significance", "-1"]) == 2
    assert "significance" in capsys.readouterr().err


def _stub_dataset(monkeypatch, tmp_path):
    import cinemate.cli as cli
    from cinemate.movielens import Rating

    ratings = [Rating(u, m, 5.0 if (u + m) % 2 else 1.0) for u in range(1, 21) for m in range(10)]
    monkeypatch.setattr(cli, "ensure_movielens", lambda dest: tmp_path)
    monkeypatch.setattr(cli, "parse_ratings", lambda path: iter(ratings))
    return cli


def test_evaluate_and_tune_read_rec_env(monkeypatch, tmp_path, capsys):
    cli = _stub_dataset(monkeypatch, tmp_path)
    monkeypatch.setenv("REC_MIN_USER_RATINGS", "7")
    monkeypatch.setenv("REC_FALLBACK_POOL_FACTOR", "1")
    import cinemate.evaluation.runner as runner

    seen = {}
    for owner, name, key in ((runner, "evaluate", "evaluate"), (cli, "tune", "tune")):
        real = getattr(owner, name)

        def spy(*args, _real=real, _key=key, **kwargs):
            seen[_key] = kwargs["settings"]
            return _real(*args, **kwargs)

        monkeypatch.setattr(owner, name, spy)
    assert main(["evaluate", "--min-overlap", "1", "--top-n", "3"]) == 0
    assert main(["tune", "--k", "5", "--lambda", "1", "--min-overlap", "1", "--top-n", "3"]) == 0
    for name in ("evaluate", "tune"):
        assert (seen[name].min_user_ratings, seen[name].fallback_pool_factor) == (7, 1)
    capsys.readouterr()


@pytest.mark.parametrize("command", ["evaluate", "tune"])
def test_evaluate_and_tune_reject_invalid_rec_env(monkeypatch, tmp_path, capsys, command):
    _stub_dataset(monkeypatch, tmp_path)
    monkeypatch.setenv("REC_MIN_USER_RATINGS", "0")
    assert main([command]) == 2
    assert "REC_MIN_USER_RATINGS" in capsys.readouterr().err
