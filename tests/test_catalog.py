from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cinemate.db.catalog import CatalogConflict, find_movie, link, merge_movies
from cinemate.db.models import Event, Movie, MovieExternalId, Rating, SeenMark, User
from cinemate.db.session import create_all, make_engine


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with Session(engine) as s:
        yield s


def _movie(session, title="A", **kw):
    movie = Movie(title=title, **kw)
    session.add(movie)
    session.flush()
    return movie


def test_find_movie_by_tmdb_pair_and_type(session):
    film = _movie(session, tmdb_type="movie", tmdb_id=1399)
    show = _movie(session, "S", tmdb_type="tv", tmdb_id=1399)
    assert find_movie(session, tmdb=("movie", 1399)) is film
    assert find_movie(session, tmdb=("tv", 1399)) is show
    assert find_movie(session, tmdb=("movie", 5)) is None
    assert find_movie(session) is None


def test_find_movie_by_external_ids_in_source_order(session):
    a, b, c = _movie(session, "a"), _movie(session, "b"), _movie(session, "c")
    link(session, a, "imdb", "tt1")
    link(session, b, "movielens", "7")
    link(session, c, "ratings_csv", "9")
    assert find_movie(session, ids={"movielens": "7", "imdb": "tt1"}) is a
    assert find_movie(session, ids={"ratings_csv": "9", "movielens": "7"}) is b
    assert find_movie(session, ids={"ratings_csv": "9"}) is c
    assert find_movie(session, ids={"kinopoisk": "1"}) is None


def test_find_movie_prefers_tmdb_pair_over_ids(session):
    a = _movie(session, "a", tmdb_type="movie", tmdb_id=1)
    b = _movie(session, "b")
    link(session, b, "imdb", "tt2")
    assert find_movie(session, tmdb=("movie", 1), ids={"imdb": "tt2"}) is a


def test_link_is_idempotent_and_rejects_other_movie(session):
    a, b = _movie(session, "a"), _movie(session, "b")
    link(session, a, "movielens", 7)
    link(session, a, "movielens", "7")
    assert session.scalars(select(MovieExternalId)).all()[0].external_id == "7"
    assert len(session.scalars(select(MovieExternalId)).all()) == 1
    with pytest.raises(CatalogConflict):
        link(session, b, "movielens", "7")
    assert find_movie(session, ids={"movielens": "7"}) is a
    # several ids of one source may point to one movie
    link(session, a, "movielens", "8")
    assert len(session.scalars(select(MovieExternalId)).all()) == 2


def test_tmdb_pair_is_unique_but_may_be_null(session):
    _movie(session, tmdb_type="movie", tmdb_id=1)
    _movie(session)
    _movie(session)
    with pytest.raises(IntegrityError):
        _movie(session, tmdb_type="movie", tmdb_id=1)


def _rate(session, user, movie, value, day):
    session.add(
        Rating(
            user_id=user.id,
            movie_id=movie.id,
            value=value,
            created_at=datetime(2026, 1, day, tzinfo=UTC),
        )
    )


def test_merge_movies(session):
    keep = _movie(session, "keep", tmdb_type="movie", tmdb_id=1)
    drop = _movie(session, "drop", overview="text", external_movielens_id=20, imdb_id="tt2")
    link(session, keep, "movielens", "10")
    link(session, drop, "movielens", "20")
    users = [User(), User(), User()]
    session.add_all(users)
    session.flush()
    both_later_drop, both_later_keep, only_drop = users
    _rate(session, both_later_drop, keep, 1, 1)
    _rate(session, both_later_drop, drop, -1, 2)
    _rate(session, both_later_keep, keep, 1, 5)
    _rate(session, both_later_keep, drop, -1, 2)
    _rate(session, only_drop, drop, 1, 1)
    session.add_all(
        [
            SeenMark(user_id=both_later_drop.id, movie_id=keep.id, type="not_seen"),
            SeenMark(user_id=both_later_drop.id, movie_id=drop.id, type="watched"),
            SeenMark(user_id=only_drop.id, movie_id=drop.id, type="not_interested"),
            Event(user_id=only_drop.id, session_id="s", type="impression", movie_id=drop.id),
        ]
    )
    session.flush()
    keep_id, drop_id = keep.id, drop.id

    merge_movies(session, keep_id, drop_id)

    assert session.get(Movie, drop_id) is None
    merged = session.get(Movie, keep_id)
    assert (merged.title, merged.overview, merged.imdb_id) == ("keep", "text", "tt2")
    assert merged.popularity_score == 2.0
    assert sorted(
        session.execute(select(Rating.user_id, Rating.value, Rating.movie_id)).all()
    ) == sorted(
        [
            (both_later_drop.id, -1, keep_id),
            (both_later_keep.id, 1, keep_id),
            (only_drop.id, 1, keep_id),
        ]
    )
    assert sorted(session.execute(select(SeenMark.user_id, SeenMark.type)).all()) == sorted(
        [(both_later_drop.id, "watched"), (only_drop.id, "not_interested")]
    )
    assert session.scalar(select(Event.movie_id)) == keep_id
    assert find_movie(session, ids={"movielens": "20"}).id == keep_id
    assert find_movie(session, ids={"movielens": "10"}).id == keep_id


def test_merge_movies_validates(session):
    a = _movie(session)
    with pytest.raises(ValueError):
        merge_movies(session, a.id, a.id)
    with pytest.raises(ValueError):
        merge_movies(session, a.id, 999)


def test_merge_moves_tmdb_pair_from_drop_to_keep(session):
    keep = _movie(session, "keep")
    drop = _movie(session, "drop", tmdb_type="movie", tmdb_id=862)
    keep_id, drop_id = keep.id, drop.id
    merge_movies(session, keep_id, drop_id)
    assert find_movie(session, tmdb=("movie", 862)).id == keep_id
    assert session.get(Movie, drop_id) is None


def test_merge_keeps_tmdb_pair_of_keep_when_both_have_one(session):
    keep = _movie(session, "keep", tmdb_type="movie", tmdb_id=1)
    drop = _movie(session, "drop", tmdb_type="movie", tmdb_id=2)
    keep_id = keep.id
    merge_movies(session, keep_id, drop.id)
    assert find_movie(session, tmdb=("movie", 1)).id == keep_id
    assert find_movie(session, tmdb=("movie", 2)) is None


# --- import_from_tmdb ---


def _details(**kw):
    from cinemate.tmdb import TmdbDetails

    base = dict(
        tmdb_type="movie",
        tmdb_id=10,
        title="Leviathan",
        original_title="Левиафан",
        year=2014,
        poster_path="/p.jpg",
        runtime=140,
        genres=["Drama"],
        imdb_id="tt2802154",
        title_ru="Левиафан",
        overview_ru="Описание",
        overview="Overview",
    )
    base.update(kw)
    return TmdbDetails(**base)


class _FakeClient:
    def __init__(self, details=None, on_fetch=None):
        self.details = details
        self.on_fetch = on_fetch
        self.calls = 0

    def fetch_details(self, tmdb_type, tmdb_id):
        self.calls += 1
        if self.on_fetch:
            self.on_fetch()
        return self.details


def test_import_from_tmdb_creates_movie_and_imdb_link(session):
    from cinemate.db.catalog import import_from_tmdb

    client = _FakeClient(_details())
    movie = import_from_tmdb(session, client, "movie", 10)
    assert (movie.title, movie.original_title, movie.title_ru) == (
        "Leviathan",
        "Левиафан",
        "Левиафан",
    )
    assert (movie.year, movie.runtime, movie.genres, movie.poster_path) == (
        2014,
        140,
        ["Drama"],
        "/p.jpg",
    )
    assert movie.overview == "Описание"
    assert find_movie(session, ids={"imdb": "tt2802154"}) is movie


def test_import_from_tmdb_falls_back_to_english_overview(session):
    from cinemate.db.catalog import import_from_tmdb

    client = _FakeClient(_details(title_ru=None, overview_ru=None))
    movie = import_from_tmdb(session, client, "movie", 10)
    assert movie.overview == "Overview"
    assert movie.title_ru is None


def test_import_from_tmdb_is_idempotent(session):
    from cinemate.db.catalog import import_from_tmdb

    client = _FakeClient(_details())
    first = import_from_tmdb(session, client, "movie", 10)
    second = import_from_tmdb(session, client, "movie", 10)
    assert first is second
    assert client.calls == 1
    assert len(session.scalars(select(Movie)).all()) == 1


def test_import_from_tmdb_unknown_pair(session):
    from cinemate.db.catalog import import_from_tmdb

    with pytest.raises(LookupError):
        import_from_tmdb(session, _FakeClient(None), "tv", 1)


def test_import_from_tmdb_imdb_taken_by_other_movie_keeps_pair(session):
    from cinemate.db.catalog import import_from_tmdb

    other = _movie(session, "other")
    link(session, other, "imdb", "tt2802154")
    movie = import_from_tmdb(session, _FakeClient(_details()), "movie", 10)
    assert movie.id != other.id
    assert find_movie(session, ids={"imdb": "tt2802154"}) is other
    assert find_movie(session, tmdb=("movie", 10)) is movie


def test_import_from_tmdb_race_returns_winner(tmp_path):
    from cinemate.db.catalog import import_from_tmdb

    engine = make_engine(f"sqlite:///{tmp_path / 'race.db'}")
    create_all(engine)

    def other_request_wins():
        with Session(engine) as other:
            other.add(Movie(title="Winner", tmdb_type="movie", tmdb_id=10))
            other.commit()

    with Session(engine) as s:
        client = _FakeClient(_details(), on_fetch=other_request_wins)
        movie = import_from_tmdb(s, client, "movie", 10)
        assert movie.title == "Winner"
        s.commit()
        assert len(s.scalars(select(Movie)).all()) == 1
