from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cinemate.binarize import MovieLensBinarizer
from cinemate.cli import main
from cinemate.db.importer import ImportStats, import_movielens
from cinemate.db.models import Movie, Rating, User
from cinemate.db.session import create_all, make_engine


def _write_dataset(path):
    (path / "movies.csv").write_text(
        "movieId,title,genres\n"
        "1,Toy Story (1995),Adventure|Animation\n"
        "2,Jumanji (1995),(no genres listed)\n",
        encoding="utf-8",
    )
    (path / "links.csv").write_text(
        "movieId,imdbId,tmdbId\n1,0114709,862\n2,0113497,\n", encoding="utf-8"
    )
    (path / "ratings.csv").write_text(
        "userId,movieId,rating,timestamp\n10,1,5.0,1\n10,2,1.0,2\n11,1,3.0,3\n11,2,4.0,4\n",
        encoding="utf-8",
    )
    return path


def _session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return Session(engine)


def _snapshot(session):
    movies = session.execute(
        select(Movie.external_movielens_id, Movie.title, Movie.imdb_id, Movie.tmdb_id)
    ).all()
    ratings = session.execute(select(Rating.user_id, Rating.movie_id, Rating.value)).all()
    users = session.execute(select(User.external_movielens_id, User.is_synthetic)).all()
    return sorted(movies), sorted(ratings), sorted(users)


def test_first_import(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        stats = import_movielens(session, data, MovieLensBinarizer())
        assert stats == ImportStats(
            movies_added=2, users_added=2, ratings_added=3, ratings_skipped=1
        )
        toy = session.scalar(select(Movie).where(Movie.external_movielens_id == 1))
        assert (toy.title, toy.year, toy.genres) == ("Toy Story", 1995, ["Adventure", "Animation"])
        assert (toy.imdb_id, toy.tmdb_id) == ("tt0114709", 862)
        jumanji = session.scalar(select(Movie).where(Movie.external_movielens_id == 2))
        assert jumanji.genres == [] and jumanji.tmdb_id is None
        assert sorted(session.scalars(select(Rating.value))) == [-1, 1, 1]


def test_users_are_synthetic(tmp_path):
    with _session() as session:
        import_movielens(session, _write_dataset(tmp_path), MovieLensBinarizer())
        users = session.scalars(select(User)).all()
        assert sorted(u.external_movielens_id for u in users) == [10, 11]
        assert all(u.is_synthetic for u in users)


def test_second_import_is_idempotent(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        import_movielens(session, data, MovieLensBinarizer())
        before = _snapshot(session)
        stats = import_movielens(session, data, MovieLensBinarizer())
        assert (stats.movies_added, stats.users_added, stats.ratings_added) == (0, 0, 0)
        assert _snapshot(session) == before


def test_reimport_updates_existing_movie(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        import_movielens(session, data, MovieLensBinarizer())
        (data / "movies.csv").write_text(
            "movieId,title,genres\n1,Toy Story 2 (1999),Animation\n2,Jumanji (1995),Fantasy\n",
            encoding="utf-8",
        )
        import_movielens(session, data, MovieLensBinarizer())
        assert session.scalar(select(func.count()).select_from(Movie)) == 2
        toy = session.scalar(select(Movie).where(Movie.external_movielens_id == 1))
        assert (toy.title, toy.year, toy.genres) == ("Toy Story 2", 1999, ["Animation"])


def test_cli_import_movielens(tmp_path, monkeypatch, capsys):
    data = _write_dataset(tmp_path)
    monkeypatch.setattr("cinemate.cli.ensure_movielens", lambda d: d)
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    args = ["import-movielens", "--database-url", url, "--data-dir", str(data)]
    assert main(args) == 0
    assert "ratings added: 3" in capsys.readouterr().out
    assert main(args) == 0
    assert "ratings added: 0" in capsys.readouterr().out
