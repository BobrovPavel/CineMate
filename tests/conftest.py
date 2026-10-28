import pytest

from cinemate.db.matrix_store import MatrixStore


@pytest.fixture(autouse=True)
def _no_matrix_warmup(request, monkeypatch):
    """Keep the startup warm-up thread out of tests that share one in-memory SQLite connection.

    ``tests/test_api_warmup.py`` exercises the real warm-up.
    """
    if request.module.__name__.endswith("test_api_warmup"):
        return
    monkeypatch.setattr(MatrixStore, "warm", lambda self, pools: None)
