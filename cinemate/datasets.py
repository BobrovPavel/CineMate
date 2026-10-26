"""Downloading and unpacking MovieLens datasets (ml-latest-small, ml-32m)."""

import hashlib
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

DATASET_DIR = "ml-latest-small"
DATASETS = ("ml-latest-small", "ml-32m")
_BASE_URL = "https://files.grouplens.org/datasets/movielens"
MOVIELENS_URL = f"{_BASE_URL}/{DATASET_DIR}.zip"
DEFAULT_DATA_DIR = Path("data")


class UnsafeArchiveError(ValueError):
    """The archive contains a member that would be extracted outside the destination."""


class ChecksumError(ValueError):
    """The downloaded archive does not match the MD5 published by GroupLens."""


def dataset_url(name: str) -> str:
    if name not in DATASETS:
        raise ValueError(f"unknown dataset {name!r}, expected one of {', '.join(DATASETS)}")
    return f"{_BASE_URL}/{name}.zip"


def _download(url: str, target: Path) -> None:
    urllib.request.urlretrieve(url, target)


def _fetch_md5(url: str) -> str | None:
    """MD5 from ``<url>.md5`` (``<hash>  <file>`` format), ``None`` if the site has no such file."""
    try:
        with urllib.request.urlopen(url + ".md5", timeout=30) as response:
            text = response.read().decode("ascii", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    words = text.split()
    return words[0].lower() if words else None


def _md5(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - integrity check against the published checksum
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _extract(archive: Path, dest: Path) -> None:
    root = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if not (root / name).resolve().is_relative_to(root):
                raise UnsafeArchiveError(f"unsafe path in archive: {name!r}")
        zf.extractall(root)


def ensure_movielens(dest: Path = DEFAULT_DATA_DIR, name: str = DATASET_DIR) -> Path:
    """Return the ``name`` dataset directory under ``dest``, downloading it if missing.

    When GroupLens publishes an MD5 file next to the archive, the download is verified against it.
    """
    url = dataset_url(name)
    dataset = dest / name
    if (dataset / "ratings.csv").exists():
        return dataset
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / f"{name}.zip"
        _download(url, archive)
        expected = _fetch_md5(url)
        if expected is not None and _md5(archive) != expected:
            raise ChecksumError(f"MD5 of {url} does not match the published checksum")
        _extract(archive, dest)
    return dataset
