import zipfile
from pathlib import Path

import pytest

from cinemate import datasets
from cinemate.datasets import UnsafeArchiveError, ensure_movielens


def _fake_download(members: dict[str, str], calls: list[str]):
    def download(url: str, target: Path) -> None:
        calls.append(url)
        with zipfile.ZipFile(target, "w") as zf:
            for name, content in members.items():
                zf.writestr(name, content)

    return download


@pytest.fixture(autouse=True)
def _no_checksum(monkeypatch):
    monkeypatch.setattr(datasets, "_fetch_md5", lambda url: None)


def test_downloads_and_extracts(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        datasets, "_download", _fake_download({"ml-latest-small/ratings.csv": "x"}, calls)
    )
    result = ensure_movielens(tmp_path)
    assert result == tmp_path / "ml-latest-small"
    assert (result / "ratings.csv").read_text() == "x"
    assert calls == [datasets.MOVIELENS_URL]


def test_second_call_does_not_download(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        datasets, "_download", _fake_download({"ml-latest-small/ratings.csv": "x"}, calls)
    )
    ensure_movielens(tmp_path)
    ensure_movielens(tmp_path)
    assert len(calls) == 1


def test_creates_missing_dest(tmp_path, monkeypatch):
    monkeypatch.setattr(
        datasets, "_download", _fake_download({"ml-latest-small/ratings.csv": "x"}, [])
    )
    dest = tmp_path / "nested" / "data"
    assert (ensure_movielens(dest) / "ratings.csv").exists()


def test_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(datasets, "_download", _fake_download({"../evil.txt": "x"}, []))
    dest = tmp_path / "data"
    with pytest.raises(UnsafeArchiveError, match="evil.txt"):
        ensure_movielens(dest)
    assert not (tmp_path / "evil.txt").exists()
    assert not (dest / "ml-latest-small").exists()


def test_rejects_absolute_path(tmp_path, monkeypatch):
    monkeypatch.setattr(datasets, "_download", _fake_download({"/tmp/evil.txt": "x"}, []))
    with pytest.raises(UnsafeArchiveError):
        ensure_movielens(tmp_path / "data")


def test_ml_32m_url_and_path(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(datasets, "_download", _fake_download({"ml-32m/ratings.csv": "x"}, calls))
    result = ensure_movielens(tmp_path, "ml-32m")
    assert result == tmp_path / "ml-32m"
    assert calls == ["https://files.grouplens.org/datasets/movielens/ml-32m.zip"]


def test_unknown_dataset_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown dataset"):
        ensure_movielens(tmp_path, "ml-1b")


def test_checksum_mismatch_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(datasets, "_download", _fake_download({"ml-32m/ratings.csv": "x"}, []))
    monkeypatch.setattr(datasets, "_fetch_md5", lambda url: "0" * 32)
    with pytest.raises(datasets.ChecksumError):
        ensure_movielens(tmp_path, "ml-32m")
    assert not (tmp_path / "ml-32m").exists()


def test_matching_checksum_is_accepted(tmp_path, monkeypatch):
    written: list[str] = []
    fake = _fake_download({"ml-32m/ratings.csv": "x"}, [])

    def download(url: str, target: Path) -> None:
        fake(url, target)
        written.append(datasets._md5(target))

    monkeypatch.setattr(datasets, "_download", download)
    monkeypatch.setattr(datasets, "_fetch_md5", lambda url: written[0])
    assert (ensure_movielens(tmp_path, "ml-32m") / "ratings.csv").exists()
