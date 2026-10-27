from sqlalchemy import select

from cinemate.binarize import RelativeMeanBinarizer
from cinemate.db.catalog import find_movie
from cinemate.db.models import Movie, MovieExternalId, Rating, User
from cinemate.db.ratings_import import import_ratings_csv
from cinemate.ratings_csv import load_ratings
from cinemate.wikidata import WikidataEntry
from tests.test_ratings_import_tmdb import (
    FakeTmdb,
    _details,
    _filler,
    _item,
    _row,
    _session,
    _write,
)


def _run(session, path, client, wikidata, use_tmdb=True):
    binarizer = RelativeMeanBinarizer.fit(load_ratings(path))
    return import_ratings_csv(
        session, path, binarizer, client=client, use_tmdb=use_tmdb, wikidata=wikidata
    )


def test_wikidata_pair_before_search(tmp_path):
    session = _session()
    client = FakeTmdb(
        [_details("movie", 5, "Heat", 1995)],
        results={"Heat": [_item("movie", 99, "Heat", 1995)]},
    )
    path = _write(tmp_path, _row(kp="7", title="Схватка", orig="Heat", year="1995") + _filler())
    stats = _run(session, path, client, {7: WikidataEntry("movie", 5, None)})
    assert find_movie(session, ids={"kinopoisk": "7"}).tmdb_id == 5
    assert stats.matched_by_wikidata == 1 and stats.matched_by_search == 0
    assert ("search", "Heat") not in client.calls


def test_wikidata_imdb_fallback_uses_find(tmp_path):
    session = _session()
    client = FakeTmdb(
        [_details("movie", 949, "Heat", 1995)],
        found={"tt0113277": _item("movie", 949, "Heat", 1995)},
    )
    path = _write(tmp_path, _row(kp="7", title="Схватка") + _filler())
    stats = _run(session, path, client, {7: WikidataEntry(None, None, "tt0113277")})
    assert find_movie(session, tmdb=("movie", 949)) is not None
    assert stats.matched_by_wikidata == 1


def test_wikidata_with_no_tmdb_uses_catalog(tmp_path):
    session = _session()
    movie = Movie(title="Heat", tmdb_type="movie", tmdb_id=5, genres=[])
    session.add(movie)
    session.commit()
    path = _write(tmp_path, _row(kp="7", title="Схватка") + _filler())
    stats = _run(session, path, FakeTmdb(), {7: WikidataEntry("movie", 5, None)}, use_tmdb=False)
    assert find_movie(session, ids={"kinopoisk": "7"}).id == movie.id
    assert stats.matched_by_wikidata == 1 and stats.unresolved == 20  # only the filler


def _unresolved_setup(session, tmp_path, body):
    path = _write(tmp_path, body + _filler())
    _run(session, path, None, None, use_tmdb=False)
    return path


def test_existing_unresolved_movie_gets_pair(tmp_path):
    session = _session()
    path = _unresolved_setup(session, tmp_path, _row(kp="7", title="Схватка"))
    movie = find_movie(session, ids={"kinopoisk": "7"})
    assert movie.tmdb_id is None
    client = FakeTmdb([_details("movie", 5, "Heat", 1995)])
    stats = _run(session, path, client, {7: WikidataEntry("movie", 5, None)})
    session.expire_all()
    movie = find_movie(session, ids={"kinopoisk": "7"})
    assert (movie.tmdb_type, movie.tmdb_id) == ("movie", 5)
    assert movie.poster_path == "/p.jpg"
    assert stats.matched_by_wikidata == 1 and stats.merged_by_wikidata == 0


def test_merge_into_pair_owner_keeps_ratings(tmp_path):
    session = _session()
    path = _unresolved_setup(session, tmp_path, _row(kp="7", title="Схватка"))
    csv_movie = find_movie(session, ids={"kinopoisk": "7"})
    csv_id = csv_movie.id
    owner = Movie(title="Heat", tmdb_type="movie", tmdb_id=5, genres=[])
    other = User(is_synthetic=True, pool="world")
    session.add_all([owner, other])
    session.flush()
    session.add(Rating(user_id=other.id, movie_id=owner.id, value=1))
    session.commit()
    owner_id = owner.id
    n_ratings = len(list(session.scalars(select(Rating).where(Rating.movie_id == csv_id))))
    assert n_ratings == 1

    stats = _run(session, path, FakeTmdb(), {7: WikidataEntry("movie", 5, None)})
    session.expire_all()
    assert session.get(Movie, csv_id) is None
    assert find_movie(session, ids={"kinopoisk": "7"}).id == owner_id
    values = list(session.scalars(select(Rating.user_id).where(Rating.movie_id == owner_id)))
    assert len(values) == 2
    assert stats.merged_by_wikidata == 1 and stats.matched_by_wikidata == 1


def test_reimport_changes_nothing(tmp_path):
    session = _session()
    path = _unresolved_setup(session, tmp_path, _row(kp="7", title="Схватка"))
    mapping = {7: WikidataEntry("movie", 5, None)}
    client = FakeTmdb([_details("movie", 5, "Heat", 1995)])
    _run(session, path, client, mapping)
    snapshot = (
        session.scalars(select(Movie.id)).all(),
        session.scalars(select(Rating.id)).all(),
        session.scalars(select(MovieExternalId.external_id)).all(),
    )
    stats = _run(session, path, client, mapping)
    assert stats.matched_by_wikidata == 0 and stats.ratings_added == 0
    assert stats.movies_added == 0
    assert snapshot == (
        session.scalars(select(Movie.id)).all(),
        session.scalars(select(Rating.id)).all(),
        session.scalars(select(MovieExternalId.external_id)).all(),
    )


def test_without_mapping_behaviour_unchanged(tmp_path):
    session = _session()
    client = FakeTmdb()
    path = _write(tmp_path, _row(kp="7", title="Схватка") + _filler())
    stats = _run(session, path, client, None)
    assert stats.matched_by_wikidata == 0 and stats.movies_added == 21
    assert find_movie(session, ids={"kinopoisk": "7"}).tmdb_id is None
