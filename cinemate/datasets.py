"""Downloading and unpacking the MovieLens ml-latest-small dataset."""

import tempfile
import urllib.request
import zipfile
from pathlib import Path

MOVIELENS_URL = "https://files.grouplens.org/datasets/movielens/ml-latest-small.zip"
DATASET_DIR = "ml-latest-small"
DEFAULT_DATA_DIR = Path("data")


class UnsafeArchiveError(ValueError):
    """The archive contains a member that would be extracted outside the destination."""


def _download(url: str, target: Path) -> None:
    urllib.request.urlretrieve(url, target)


def _extract(archive: Path, dest: Path) -> None:
    root = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if not (root / name).resolve().is_relative_to(root):
                raise UnsafeArchiveError(f"unsafe path in archive: {name!r}")
        zf.extractall(root)


def ensure_movielens(dest: Path = DEFAULT_DATA_DIR) -> Path:
    """Return the ml-latest-small directory under ``dest``, downloading it if missing."""
    dataset = dest / DATASET_DIR
    if (dataset / "ratings.csv").exists():
        return dataset
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "ml-latest-small.zip"
        _download(MOVIELENS_URL, archive)
        _extract(archive, dest)
    return dataset
