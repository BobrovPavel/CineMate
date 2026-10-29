import json

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cinemate.api.app import create_app
from cinemate.cli import main
from cinemate.db.catalog import import_from_tmdb, merge_movies
from cinemate.db.enrich import enrich_movies
from cinemate.db.features import genre_names_by_movie
from cinemate.db.migrations import alembic_config, upgrade_head
from cinemate.db.models import Collection, Company, Movie, MovieCompany, MovieGenre, Rating, User
from cinemate.db.session import create_all, make_engine
from cinemate.genres import legacy_genre_ids, tmdb_genre_ids
from cinemate.tmdb import TmdbClient


def _client(payload):
    return TmdbClient("k", http_get=lambda url: (200, json.dumps(payload).encode()))


MOVIE_PAYLOAD = {
    "title": "Iron Man",
    "original_title": "Iron Man",
    "release_date": "2008-04-30",
    "genres": [{"id": 28, "name": "Action"}, {"id": 878, "name": "Science Fiction"}],
    "belongs_to_collection": {"id": 131292, "name": "Iron Man Collection"},
    "production_companies": [
        {"id": 420, "name": "Marvel Studios", "logo_path": "/m.png"},
        {"id": 7, "name": "No Logo", "logo_path": None},
    ],
    "production_countries": [{"iso_3166_1": "US", "name": "United States"}],
    "original_language": "en",
    "vote_average": 7.6,
    "vote_count": 25000,
}
TV_PAYLOAD = {
    "name": "Show",
    "first_air_date": "2020-01-01",
    "genres": [{"id": 10759, "name": "Action & Adventure"}, {"id": 10765, "name": "Sci-Fi"}],
    "production_companies": [],
    "origin_country": ["GB", "US"],
    "original_language": "en",
    "vote_average": 8,
    "vote_count": 10,
}


def _session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return Session(engine)


def _names(session, movie, lang="en"):
    return genre_names_by_movie(session, [movie.id], lang).get(movie.id, [])


def test_legacy_names_movielens_and_kinopoisk():
    assert legacy_genre_ids(["Adventure", "Children", "IMAX", "Film-Noir", "Crime"]) == (
        [12, 10751, 80],
        ["IMAX"],
    )
    assert legacy_genre_ids(["(no genres listed)"]) == ([], ["(no genres listed)"])
    assert legacy_genre_ids(["Боевик", "аниме", "реальное ТВ", "биография", "спорт"]) == (
        [28, 16, 10764],
        ["биография", "спорт"],
    )


def test_tv_genres_are_split_and_unknown_dropped():
    assert tmdb_genre_ids([10759, 10765, 10768, 10762, 99999, 28]) == [
        28,
        12,
        878,
        14,
        10752,
        10762,
    ]


def test_parse_movie_details():
    details = _client(MOVIE_PAYLOAD).fetch_details("movie", 1726)
    assert details.genre_ids == [28, 878]
    assert details.collection == (131292, "Iron Man Collection")
    assert details.companies == [(420, "Marvel Studios", "/m.png"), (7, "No Logo", None)]
    assert details.countries == ["US"]
    assert (details.original_language, details.vote_average, details.vote_count) == (
        "en",
        7.6,
        25000,
    )


def test_parse_tv_details():
    details = _client(TV_PAYLOAD).fetch_details("tv", 5)
    assert details.genre_ids == [10759, 10765]
    assert details.collection is None
    assert details.countries == ["GB", "US"]
    assert (details.vote_average, details.vote_count) == (8.0, 10)


def test_import_from_tmdb_writes_features():
    session = _session()
    movie = import_from_tmdb(session, _client(MOVIE_PAYLOAD), "movie", 1726)
    session.commit()
    assert _names(session, movie) == ["Action", "Science Fiction"]
    assert _names(session, movie, "ru") == ["боевик", "фантастика"]
    assert movie.collection_id == 131292
    assert session.get(Collection, 131292).name == "Iron Man Collection"
    assert session.get(Company, 420).logo_path == "/m.png"
    assert set(session.scalars(select(MovieCompany.company_id))) == {420, 7}
    assert (movie.countries, movie.original_language) == (["US"], "en")
    assert (movie.tmdb_vote_average, movie.tmdb_vote_count) == (7.6, 25000)


def test_tv_composite_genres_become_movie_genres():
    session = _session()
    movie = import_from_tmdb(session, _client(TV_PAYLOAD), "tv", 5)
    assert _names(session, movie) == ["Adventure", "Fantasy", "Action", "Science Fiction"]


def test_enrich_overwrites_old_genres_with_tmdb_ones():
    session = _session()
    movie = Movie(title="Iron Man", tmdb_type="movie", tmdb_id=1726)
    session.add(movie)
    session.flush()
    session.execute(MovieGenre.__table__.insert(), [{"movie_id": movie.id, "genre_id": 18}])
    session.commit()
    enrich_movies(session, _client(MOVIE_PAYLOAD))
    assert _names(session, movie) == ["Action", "Science Fiction"]


def test_missing_features_rated_movies_first():
    session = _session()
    user = User(is_synthetic=True)
    session.add(user)
    done = Movie(title="done", tmdb_type="movie", tmdb_id=1, tmdb_vote_count=5)
    unrated = Movie(title="unrated", tmdb_type="movie", tmdb_id=2)
    rated = Movie(title="rated", tmdb_type="movie", tmdb_id=3)
    nopair = Movie(title="nopair")
    session.add_all([done, unrated, rated, nopair])
    session.flush()
    session.add(Rating(user_id=user.id, movie_id=rated.id, value=1))
    session.commit()

    requested = []

    class Fake(TmdbClient):
        def __init__(self):
            pass

        def fetch_details(self, tmdb_type, tmdb_id):
            requested.append(tmdb_id)
            return _client(MOVIE_PAYLOAD).fetch_details(tmdb_type, tmdb_id)

    stats = enrich_movies(session, Fake(), missing_features=True)
    assert requested == [3, 2]
    assert (stats.enriched, stats.skipped) == (2, 1)
    assert enrich_movies(session, Fake(), missing_features=True).enriched == 0
    assert requested == [3, 2]

    requested.clear()
    session.add(Movie(title="another", tmdb_type="movie", tmdb_id=9))
    session.commit()
    enrich_movies(session, Fake(), missing_features=True, limit=1)
    assert requested == [9]


def test_cli_missing_features_flag(monkeypatch):
    seen = {}

    def fake(session, client, **kwargs):
        seen.update(kwargs)
        from cinemate.db.enrich import EnrichStats

        return EnrichStats(0, 0)

    monkeypatch.setenv("TMDB_API_KEY", "k")
    monkeypatch.setattr("cinemate.cli.enrich_movies", fake)
    assert (
        main(["enrich-movies", "--database-url", "sqlite:///:memory:", "--missing-features"]) == 0
    )
    assert seen["missing_features"] is True


def test_merge_moves_features():
    session = _session()
    keep = Movie(title="keep")
    drop = Movie(title="drop", collection_id=None)
    session.add_all([keep, drop])
    session.add_all([Company(id=1, name="A"), Company(id=2, name="B")])
    session.flush()
    session.execute(MovieGenre.__table__.insert(), [{"movie_id": drop.id, "genre_id": 35}])
    session.execute(
        MovieCompany.__table__.insert(),
        [{"movie_id": drop.id, "company_id": 1}, {"movie_id": drop.id, "company_id": 2}],
    )
    session.commit()
    merge_movies(session, keep.id, drop.id)
    session.commit()
    assert _names(session, keep) == ["Comedy"]
    assert set(session.scalars(select(MovieCompany.company_id))) == {1, 2}
    assert session.scalars(select(MovieCompany.movie_id)).all() == [keep.id, keep.id]


def test_migration_translates_old_genres(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'm.db'}")
    command.upgrade(alembic_config(engine), "0010")
    rows = [
        (1, ["Adventure", "Children", "IMAX"]),
        (2, ["(no genres listed)"]),
        (3, ["драма", "биография", "реальное ТВ"]),
        (4, ["Film-Noir", "Crime"]),
        (5, ["Science Fiction", "Action & Adventure"]),
        (6, []),
    ]
    with engine.begin() as conn:
        for movie_id, genres in rows:
            conn.execute(
                text("INSERT INTO movies (id, title, genres) VALUES (:i, 't', :g)"),
                {"i": movie_id, "g": json.dumps(genres, ensure_ascii=False)},
            )
    upgrade_head(engine)
    with engine.connect() as conn:
        found: dict[int, list[int]] = {}
        for movie_id, genre_id in conn.execute(
            text("SELECT movie_id, genre_id FROM movie_genres ORDER BY 1, 2")
        ):
            found.setdefault(movie_id, []).append(genre_id)
        assert conn.execute(text("SELECT count(*) FROM genres")).scalar() == 24
    assert found == {1: [12, 10751], 3: [18, 10764], 4: [80], 5: [12, 28, 878]}


def test_api_genres_follow_request_language():
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        session.add(Movie(id=1, title="A"))
        session.flush()
        session.add_all([MovieGenre(movie_id=1, genre_id=18), MovieGenre(movie_id=1, genre_id=35)])
        session.commit()
    with TestClient(app) as client:
        client.post("/api/session")
        assert client.get("/api/movies/1", headers={"accept-language": "en"}).json()["genres"] == [
            "Drama",
            "Comedy",
        ]
        ru = client.get("/api/movies/1", headers={"accept-language": "ru"}).json()
        assert ru["genres"] == ["драма", "комедия"]
