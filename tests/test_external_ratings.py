import gzip
import os
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cinemate.cli import main
from cinemate.db import external_ratings
from cinemate.db.external_ratings import (
    ensure_imdb_ratings,
    import_imdb_ratings,
    read_imdb_ratings,
    upsert_external_ratings,
)
from cinemate.db.models import ExternalRating, Movie, MovieExternalId
from cinemate.db.session import create_all, make_engine

TSV = (
    "tconst\taverageRating\tnumVotes\n"
    "tt0000001\t5.7\t2000\ntt0000002\t6.0\t300\ntt0000003\t8.1\t12\n"
)


def _session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return Session(engine)


def _gz(tmp_path, text=TSV, name="title.ratings.tsv.gz"):
    path = tmp_path / name
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(text)
    return path


def _movie(session, title, *imdb_ids):
    movie = Movie(title=title)
    session.add(movie)
    session.flush()
    for imdb_id in imdb_ids:
        session.add(MovieExternalId(source="imdb", external_id=imdb_id, movie_id=movie.id))
    session.flush()
    return movie


def _stored(session):
    return {
        (r.movie_id, r.source): (r.value, r.votes) for r in session.scalars(select(ExternalRating))
    }


def test_read_ratings_streams_rows(tmp_path):
    assert list(read_imdb_ratings(_gz(tmp_path))) == [
        ("tt0000001", 5.7, 2000),
        ("tt0000002", 6.0, 300),
        ("tt0000003", 8.1, 12),
    ]


def test_read_ratings_bad_input(tmp_path):
    with pytest.raises(ValueError, match="expected columns"):
        list(read_imdb_ratings(_gz(tmp_path, "a\tb\n1\t2\n")))
    with pytest.raises(ValueError, match="line 2"):
        list(read_imdb_ratings(_gz(tmp_path, "tconst\taverageRating\tnumVotes\ntt1\tx\t3\n")))


def test_import_matches_by_imdb_id(tmp_path):
    session = _session()
    a = _movie(session, "A", "tt0000001")
    b = _movie(session, "B", "tt0000003")
    _movie(session, "No IMDb id")
    stats = import_imdb_ratings(session, _gz(tmp_path))
    assert (stats.rows, stats.matched, stats.updated) == (3, 2, 2)
    assert _stored(session) == {(a.id, "imdb"): (5.7, 2000), (b.id, "imdb"): (8.1, 12)}


def test_second_run_has_no_duplicates_and_updates_changes(tmp_path):
    session = _session()
    a = _movie(session, "A", "tt0000001")
    import_imdb_ratings(session, _gz(tmp_path))
    stats = import_imdb_ratings(session, _gz(tmp_path))
    assert (stats.matched, stats.updated) == (1, 0)
    assert len(_stored(session)) == 1
    newer = _gz(tmp_path, TSV.replace("5.7\t2000", "5.9\t2100"), "new.tsv.gz")
    stats = import_imdb_ratings(session, newer)
    assert stats.updated == 1
    assert _stored(session) == {(a.id, "imdb"): (5.9, 2100)}


def test_movie_with_two_imdb_ids_keeps_most_voted(tmp_path):
    session = _session()
    a = _movie(session, "A", "tt0000001", "tt0000002")
    import_imdb_ratings(session, _gz(tmp_path))
    assert _stored(session) == {(a.id, "imdb"): (5.7, 2000)}


def test_upsert_writes_in_batches(monkeypatch):
    monkeypatch.setattr(external_ratings, "BATCH_SIZE", 2)
    session = _session()
    movies = [_movie(session, f"M{i}") for i in range(5)]
    ratings = {m.id: (float(i), i) for i, m in enumerate(movies)}
    assert upsert_external_ratings(session, "imdb", ratings) == 5
    ratings[movies[0].id] = (9.0, 1)
    ratings[movies[4].id] = (1.0, 1)
    assert upsert_external_ratings(session, "imdb", ratings) == 2
    assert _stored(session)[(movies[4].id, "imdb")] == (1.0, 1)
    assert len(_stored(session)) == 5


def test_source_is_restricted():
    session = _session()
    movie = _movie(session, "A")
    session.add(
        ExternalRating(movie_id=movie.id, source="rt", value=1.0, updated_at=datetime.now(UTC))
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_ensure_downloads_once_a_day(tmp_path, monkeypatch):
    calls = []

    def fake(url, target):
        calls.append(url)
        target.write_bytes(b"x")

    monkeypatch.setattr(external_ratings, "_download", fake)
    path = ensure_imdb_ratings(tmp_path / "imdb")
    assert path.read_bytes() == b"x" and len(calls) == 1
    ensure_imdb_ratings(tmp_path / "imdb")
    assert len(calls) == 1
    old = (datetime.now() - timedelta(days=2)).timestamp()
    os.utime(path, (old, old))
    ensure_imdb_ratings(tmp_path / "imdb")
    assert len(calls) == 2
    ensure_imdb_ratings(tmp_path / "imdb", today=date.today() + timedelta(days=1))
    assert len(calls) == 3


def test_cli_import_imdb_ratings(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = make_engine(url)
    create_all(engine)
    with Session(engine) as session:
        _movie(session, "A", "tt0000001")
        session.commit()
    args = ["import-imdb-ratings", "--file", str(_gz(tmp_path)), "--database-url", url]
    assert main(args) == 0
    assert "rows in dataset: 3, matched: 1, updated: 1" in capsys.readouterr().out
    assert main(args) == 0
    assert "updated: 0" in capsys.readouterr().out


def test_cli_bad_file_exits_2(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    assert (
        main(["import-imdb-ratings", "--file", str(tmp_path / "no.gz"), "--database-url", url]) == 2
    )
    bad = tmp_path / "bad.gz"
    bad.write_bytes(b"not gzip")
    assert main(["import-imdb-ratings", "--file", str(bad), "--database-url", url]) == 2
    assert "error" in capsys.readouterr().err
