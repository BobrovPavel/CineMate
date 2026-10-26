import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cinemate.binarize import RelativeMeanBinarizer
from cinemate.cli import main
from cinemate.db.catalog import find_movie
from cinemate.db.models import Movie, MovieExternalId, Rating, TmdbLookup
from cinemate.db.ratings_import import import_ratings_csv
from cinemate.db.session import create_all, make_engine
from cinemate.ratings_csv import load_ratings
from cinemate.tmdb import TmdbDetails, TmdbSearchItem

HEADER = "user_id,kp_id,tmdb_type,tmdb_id,imdb_id,title_ru,title_original,type,year,user_rating\n"


class FakeTmdb:
    def __init__(self, details=(), found=None, results=None):
        self.details = {(d.tmdb_type, d.tmdb_id): d for d in details}
        self.found = found or {}
        self.results = results or {}
        self.calls = []

    def fetch_details(self, tmdb_type, tmdb_id):
        self.calls.append(("details", tmdb_type, tmdb_id))
        return self.details.get((tmdb_type, tmdb_id))

    def find_by_imdb(self, imdb_id):
        self.calls.append(("find", imdb_id))
        return self.found.get(imdb_id)

    def search(self, query, language, page=1):
        self.calls.append(("search", query))
        return self.results.get(query, [])


def _details(tmdb_type, tmdb_id, title, year, imdb_id=None):
    return TmdbDetails(tmdb_type, tmdb_id, title, title, year, "/p.jpg", 100, [], imdb_id)


def _item(tmdb_type, tmdb_id, title, year):
    return TmdbSearchItem(tmdb_type, tmdb_id, title, title, year, None)


def _session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return Session(engine)


def _write(tmp_path, body):
    path = tmp_path / "ratings.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def _filler(first=5000):
    # a user with enough ratings (mean 5.5) so that the binarizer keeps them
    return "".join(
        f"1,{first + i},,,,Ф{first + i},F{first + i},Film,2000,{10 if i < 10 else 1}\n"
        for i in range(20)
    )


def _run(session, path, client, use_tmdb=True):
    binarizer = RelativeMeanBinarizer.fit(load_ratings(path))
    return import_ratings_csv(session, path, binarizer, client=client, use_tmdb=use_tmdb)


def _row(kp="", tmdb_type="", tmdb_id="", imdb="", title="", orig="", type_="Film", year="2000"):
    return f"1,{kp},{tmdb_type},{tmdb_id},{imdb},{title},{orig},{type_},{year},10\n"


def test_match_by_tmdb_pair_imports_from_tmdb(tmp_path):
    session = _session()
    client = FakeTmdb([_details("tv", 1399, "Game of Thrones", 2011, "tt0944947")])
    path = _write(tmp_path, _row(kp="7", tmdb_type="tv", tmdb_id="1399") + _filler())
    stats = _run(session, path, client)
    movie = find_movie(session, tmdb=("tv", 1399))
    assert movie.title == "Game of Thrones"
    assert find_movie(session, ids={"kinopoisk": "7"}) is movie
    assert find_movie(session, ids={"imdb": "tt0944947"}) is movie
    assert stats.matched_by_tmdb == 1


def test_match_by_imdb_in_catalog_without_tmdb_request(tmp_path):
    session = _session()
    movie = Movie(title="Heat", genres=[])
    session.add(movie)
    session.flush()
    session.add(MovieExternalId(source="imdb", external_id="tt0113277", movie_id=movie.id))
    session.commit()
    client = FakeTmdb()
    stats = _run(session, _write(tmp_path, _row(kp="9", imdb="tt0113277") + _filler()), client)
    assert find_movie(session, ids={"kinopoisk": "9"}).id == movie.id
    assert stats.matched_by_imdb == 1
    assert ("find", "tt0113277") not in client.calls


def test_match_by_imdb_via_tmdb_find(tmp_path):
    session = _session()
    client = FakeTmdb(
        [_details("movie", 949, "Heat", 1995, "tt0113277")],
        found={"tt0113277": _item("movie", 949, "Heat", 1995)},
    )
    stats = _run(session, _write(tmp_path, _row(kp="9", imdb="tt0113277") + _filler()), client)
    assert find_movie(session, tmdb=("movie", 949)) is not None
    assert stats.matched_by_imdb == 1


def test_match_by_kinopoisk_id_including_old_ratings_csv_link(tmp_path):
    session = _session()
    old = Movie(title="Old", genres=[], external_ratings_id=11)
    new = Movie(title="New", genres=[])
    session.add_all([old, new])
    session.flush()
    session.add(MovieExternalId(source="ratings_csv", external_id="11", movie_id=old.id))
    session.add(MovieExternalId(source="kinopoisk", external_id="12", movie_id=new.id))
    session.commit()
    body = _row(kp="11", title="Old") + _row(kp="12", title="New") + _filler()
    stats = _run(session, _write(tmp_path, body), FakeTmdb(), use_tmdb=False)
    assert stats.matched_by_kinopoisk == 2
    assert session.scalar(select(func.count()).select_from(Rating)) == 2 + 20


def test_match_by_search_movie_and_year_off_by_one(tmp_path):
    session = _session()
    client = FakeTmdb(
        [_details("movie", 949, "Heat", 1996)],
        results={"Heat": [_item("movie", 949, "Heat", 1996)]},
    )
    body = _row(kp="9", orig="Heat", year="1995") + _filler()
    stats = _run(session, _write(tmp_path, body), client)
    assert find_movie(session, tmdb=("movie", 949)) is find_movie(session, ids={"kinopoisk": "9"})
    assert stats.matched_by_search == 1


def test_search_year_off_by_two_is_rejected(tmp_path):
    session = _session()
    client = FakeTmdb(results={"Heat": [_item("movie", 949, "Heat", 1997)]})
    body = _row(kp="9", orig="Heat", year="1995") + _filler()
    stats = _run(session, _write(tmp_path, body), client)
    assert stats.matched_by_search == 0
    assert stats.unresolved >= 1
    assert find_movie(session, ids={"kinopoisk": "9"}).tmdb_id is None


def test_ambiguous_search_is_unresolved(tmp_path):
    session = _session()
    client = FakeTmdb(
        results={"Heat": [_item("movie", 1, "Heat", 1995), _item("movie", 2, "Heat", 1995)]}
    )
    body = _row(kp="9", orig="Heat", year="1995") + _filler()
    stats = _run(session, _write(tmp_path, body), client)
    assert stats.matched_by_search == 0
    movie = find_movie(session, ids={"kinopoisk": "9"})
    assert movie.tmdb_id is None
    assert stats.unresolved >= 1


def test_series_is_searched_in_tv(tmp_path):
    session = _session()
    client = FakeTmdb(
        [_details("tv", 5, "Fargo", 2014)],
        results={"Fargo": [_item("movie", 4, "Fargo", 2014), _item("tv", 5, "Fargo", 2014)]},
    )
    body = _row(kp="9", orig="Fargo", type_="TvSeries", year="2014") + _filler()
    _run(session, _write(tmp_path, body), client)
    movie = find_movie(session, ids={"kinopoisk": "9"})
    assert (movie.tmdb_type, movie.tmdb_id) == ("tv", 5)


def test_russian_title_is_used_when_original_is_empty(tmp_path):
    session = _session()
    client = FakeTmdb(
        [_details("movie", 3, "Жара", 1995)], results={"Жара": [_item("movie", 3, "Жара", 1995)]}
    )
    _run(session, _write(tmp_path, _row(kp="9", title="Жара", year="1995") + _filler()), client)
    assert find_movie(session, tmdb=("movie", 3)) is not None


def test_found_pair_is_attached_to_movie_known_only_by_kinopoisk_id(tmp_path):
    session = _session()
    movie = Movie(title="Heat", genres=[], year=1995)
    session.add(movie)
    session.flush()
    session.add(MovieExternalId(source="kinopoisk", external_id="9", movie_id=movie.id))
    session.commit()
    movie_id = movie.id
    client = FakeTmdb(
        [_details("movie", 949, "Heat", 1995)],
        results={"Heat": [_item("movie", 949, "Heat", 1995)]},
    )
    stats = _run(
        session, _write(tmp_path, _row(kp="9", orig="Heat", year="1995") + _filler()), client
    )
    found = find_movie(session, tmdb=("movie", 949))
    assert found.id == movie_id
    assert found.poster_path == "/p.jpg"
    assert stats.matched_by_kinopoisk == 1
    assert session.scalar(select(func.count()).select_from(Movie).where(Movie.title == "Heat")) == 1


def test_second_run_is_idempotent_and_makes_no_tmdb_requests(tmp_path):
    session = _session()
    client = FakeTmdb(
        [_details("movie", 949, "Heat", 1995, "tt0113277"), _details("movie", 3, "Жара", 1995)],
        found={"tt0113277": _item("movie", 949, "Heat", 1995)},
        results={"Heat": [_item("movie", 949, "Heat", 1995)]},
    )
    body = (
        _row(kp="1", imdb="tt0113277")
        + _row(kp="2", orig="Heat", year="1995")
        + _row(kp="3", orig="Nothing", title="Ничто", year="1995")
        + _filler()
    )
    path = _write(tmp_path, body)
    first = _run(session, path, client)
    assert client.calls
    movies = session.scalar(select(func.count()).select_from(Movie))
    ratings = session.scalar(select(func.count()).select_from(Rating))
    links = session.scalar(select(func.count()).select_from(MovieExternalId))
    assert session.scalar(select(func.count()).select_from(TmdbLookup)) >= 2

    client.calls.clear()
    second = _run(session, path, client)
    assert client.calls == []
    assert session.scalar(select(func.count()).select_from(Movie)) == movies
    assert session.scalar(select(func.count()).select_from(Rating)) == ratings
    assert session.scalar(select(func.count()).select_from(MovieExternalId)) == links
    assert second.movies_added == 0
    assert second.ratings_added == 0
    assert second.unresolved == first.unresolved


def test_no_tmdb_skips_find_and_search(tmp_path):
    session = _session()
    client = FakeTmdb(
        found={"tt1": _item("movie", 1, "A", 2000)}, results={"A": [_item("movie", 1, "A", 2000)]}
    )
    body = _row(kp="1", imdb="tt1", title="А") + _row(kp="2", orig="A") + _filler()
    stats = _run(session, _write(tmp_path, body), client, use_tmdb=False)
    assert client.calls == []
    assert stats.unresolved >= 2
    assert find_movie(session, ids={"imdb": "tt1"}) is not None


def test_conflicting_link_is_counted_not_moved(tmp_path):
    session = _session()
    other = Movie(title="Other", genres=[])
    session.add(other)
    session.flush()
    session.add(MovieExternalId(source="kinopoisk", external_id="9", movie_id=other.id))
    session.commit()
    client = FakeTmdb([_details("movie", 949, "Heat", 1995)])
    stats = _run(
        session,
        _write(tmp_path, _row(kp="9", tmdb_type="movie", tmdb_id="949") + _filler()),
        client,
    )
    assert stats.conflicts == 1
    assert find_movie(session, ids={"kinopoisk": "9"}).id == other.id


def test_evaluate_with_new_columns(tmp_path, capsys):
    rows = []
    for user in range(1, 8):
        for i in range(25):
            score = 10 if (i + user) % 3 else 1
            rows.append(f"{user},,movie,{100 + i},,{score}\n")
    path = tmp_path / "r.csv"
    path.write_text("user_id,kp_id,tmdb_type,tmdb_id,imdb_id,user_rating\n" + "".join(rows))
    assert main(["evaluate", "--source", "csv", "--ratings-csv", str(path)]) == 0
    assert capsys.readouterr().out


def test_cli_import_without_api_key_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    path = _write(tmp_path, _row(kp="1", orig="A") + _filler())
    db = f"sqlite:///{tmp_path / 'db.sqlite'}"
    assert main(["migrate", "--database-url", db]) == 0
    assert main(["import-ratings-csv", "--file", str(path), "--database-url", db]) == 0
    captured = capsys.readouterr()
    assert "TMDB_API_KEY is not set" in captured.err
    assert "unresolved:" in captured.out


@pytest.mark.parametrize("flag", [[], ["--no-tmdb"]])
def test_cli_accepts_no_tmdb_flag(tmp_path, monkeypatch, flag):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    path = _write(tmp_path, _row(kp="1", orig="A") + _filler())
    db = f"sqlite:///{tmp_path / 'db.sqlite'}"
    assert main(["migrate", "--database-url", db]) == 0
    assert main(["import-ratings-csv", "--file", str(path), "--database-url", db, *flag]) == 0


def test_stale_tmdb_answer_falls_through(tmp_path):
    session = _session()
    # /find and search return ids whose details are unknown to TMDB
    client = FakeTmdb(
        found={"tt1": _item("movie", 1, "A", 2000)}, results={"A": [_item("movie", 2, "A", 2000)]}
    )
    body = _row(kp="1", imdb="tt1", title="А", orig="A") + _filler()
    stats = _run(session, _write(tmp_path, body), client)
    movie = find_movie(session, ids={"kinopoisk": "1"})
    assert movie is not None and movie.tmdb_id is None
    assert stats.unresolved >= 1
