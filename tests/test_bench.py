import pytest

from cinemate.bench import fill_synthetic, format_bench, run_bench
from cinemate.cli import main
from cinemate.db.session import create_all, make_engine


def test_synthetic_bench_runs():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    count = fill_synthetic(engine, 3000, "world", seed=1)
    assert 2500 < count <= 3000
    result = run_bench(engine, "world", requests=3, seed=1)
    assert result.nonzero == count
    assert result.requests == 3
    assert "p95" in format_bench(result)


def test_synthetic_needs_empty_database():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    fill_synthetic(engine, 500, "world")
    with pytest.raises(ValueError, match="empty"):
        fill_synthetic(engine, 500, "world")


def test_empty_pool_is_an_error():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with pytest.raises(ValueError, match="no ratings"):
        run_bench(engine, "ru", requests=1, seed=0)


def test_cli_bench(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'b.db'}"
    assert (
        main(
            [
                "bench-recommendations",
                "--database-url",
                url,
                "--synthetic",
                "2000",
                "--requests",
                "2",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "matrix load" in out and "p50" in out
    assert main(["bench-recommendations", "--database-url", url, "--requests", "0"]) == 2
