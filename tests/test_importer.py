import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cinemate.binarize import MovieLensBinarizer
from cinemate.cli import main
from cinemate.db.catalog import find_movie, merge_movies
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
            movies_added=2,
            users_added=2,
            ratings_added=3,
            ratings_skipped=1,
            popularity_updated=2,
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
        assert {u.pool for u in users} == {"world"}


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
    monkeypatch.setattr("cinemate.cli.ensure_movielens", lambda d, name="ml-latest-small": d)
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    args = ["import-movielens", "--database-url", url, "--data-dir", str(data)]
    assert main(args) == 0
    assert "ratings added: 3" in capsys.readouterr().out
    assert main(args) == 0
    assert "ratings added: 0" in capsys.readouterr().out


def test_rating_for_unknown_movie_is_skipped(tmp_path):
    data = _write_dataset(tmp_path)
    with (data / "ratings.csv").open("a", encoding="utf-8") as f:
        f.write("10,999,5.0,5\n")
    with _session() as session:
        stats = import_movielens(session, data, MovieLensBinarizer())
        assert stats.ratings_added == 3
        assert stats.ratings_skipped == 2


def test_user_external_id_is_unique():
    with _session() as session:
        session.add_all([User(external_movielens_id=1), User(external_movielens_id=1)])
        with pytest.raises(IntegrityError):
            session.commit()


def test_reimport_keeps_existing_rating(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        import_movielens(session, data, MovieLensBinarizer())
        rating = session.scalars(select(Rating).order_by(Rating.id)).first()
        rating.value = -rating.value
        session.commit()
        flipped = rating.value
        import_movielens(session, data, MovieLensBinarizer())
        assert session.scalars(select(Rating).order_by(Rating.id)).first().value == flipped


def test_popularity_score_counts_likes(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        import_movielens(session, data, MovieLensBinarizer())
        scores = dict(
            session.execute(select(Movie.external_movielens_id, Movie.popularity_score)).all()
        )
        # movie 1: likes from users 10 (5.0); user 11's 3.0 is discarded. movie 2: 1.0 dislike,
        # 4.0 like.
        assert scores == {1: 1.0, 2: 1.0}


def test_popularity_score_zero_for_movies_without_likes(tmp_path):
    data = _write_dataset(tmp_path)
    (data / "ratings.csv").write_text(
        "userId,movieId,rating,timestamp\n10,1,5.0,1\n10,2,1.0,2\n", encoding="utf-8"
    )
    with _session() as session:
        stats = import_movielens(session, data, MovieLensBinarizer())
        scores = dict(
            session.execute(select(Movie.external_movielens_id, Movie.popularity_score)).all()
        )
        assert scores == {1: 1.0, 2: 0.0}
        assert stats.popularity_updated == 2


def test_popularity_score_is_idempotent(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        import_movielens(session, data, MovieLensBinarizer())
        before = sorted(session.execute(select(Movie.id, Movie.popularity_score)).all())
        stats = import_movielens(session, data, MovieLensBinarizer())
        after = sorted(session.execute(select(Movie.id, Movie.popularity_score)).all())
        assert before == after
        assert stats.popularity_updated == 0


def test_popularity_score_recomputed_when_ratings_change(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        import_movielens(session, data, MovieLensBinarizer())
        (data / "ratings.csv").write_text(
            "userId,movieId,rating,timestamp\n10,1,5.0,1\n10,2,1.0,2\n11,1,3.0,3\n"
            "11,2,4.0,4\n12,1,5.0,5\n",
            encoding="utf-8",
        )
        stats = import_movielens(session, data, MovieLensBinarizer())
        scores = dict(
            session.execute(select(Movie.external_movielens_id, Movie.popularity_score)).all()
        )
        assert scores == {1: 2.0, 2: 1.0}
        assert stats.popularity_updated == 1


def _write_titles(data, titles):
    rows = "".join(f'{i},"{t}",Drama\n' for i, t in enumerate(titles, start=1))
    (data / "movies.csv").write_text("movieId,title,genres\n" + rows, encoding="utf-8")


def test_import_normalizes_titles_and_keeps_tmdb_original_title(tmp_path):
    data = _write_dataset(tmp_path)
    _write_titles(
        data,
        [
            "City of Lost Children, The (Cité des enfants perdus, La) (1995)",
            "Blair Witch Project, The (1999)",
        ],
    )
    with _session() as session:
        import_movielens(session, data, MovieLensBinarizer())
        first = session.scalar(select(Movie).where(Movie.external_movielens_id == 1))
        second = session.scalar(select(Movie).where(Movie.external_movielens_id == 2))
        assert (first.title, first.original_title) == (
            "The City of Lost Children",
            "La Cité des enfants perdus",
        )
        assert (second.title, second.original_title) == ("The Blair Witch Project", None)
        first.original_title = "La Cité des enfants perdus (TMDB)"
        session.commit()
        import_movielens(session, data, MovieLensBinarizer())
        assert first.original_title == "La Cité des enfants perdus (TMDB)"


def test_reimport_fixes_old_titles(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        import_movielens(session, data, MovieLensBinarizer())
        toy = session.scalar(select(Movie).where(Movie.external_movielens_id == 1))
        toy.title = "Toy Story, The"
        session.commit()
        _write_titles(data, ["Blair Witch Project, The (1999)", "Jumanji (1995)"])
        import_movielens(session, data, MovieLensBinarizer())
        assert toy.title == "The Blair Witch Project"


def test_import_writes_external_ids_and_tmdb_pair(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        import_movielens(session, data, MovieLensBinarizer())
        toy = session.scalar(select(Movie).where(Movie.title == "Toy Story"))
        assert (toy.tmdb_type, toy.tmdb_id) == ("movie", 862)
        assert find_movie(session, ids={"movielens": "1"}) is toy
        assert find_movie(session, ids={"imdb": "tt0114709"}) is toy
        assert find_movie(session, tmdb=("movie", 862)) is toy


def test_import_links_movielens_duplicates_to_one_movie_and_is_idempotent(tmp_path):
    (tmp_path / "movies.csv").write_text(
        "movieId,title,genres\n1,Heat (1995),Crime\n2,Heat (1995),Crime\n", encoding="utf-8"
    )
    (tmp_path / "links.csv").write_text(
        "movieId,imdbId,tmdbId\n1,0113277,949\n2,0113277,949\n", encoding="utf-8"
    )
    (tmp_path / "ratings.csv").write_text(
        "userId,movieId,rating,timestamp\n10,1,5.0,1\n10,2,5.0,2\n11,2,5.0,3\n", encoding="utf-8"
    )
    with _session() as session:
        first = import_movielens(session, tmp_path, MovieLensBinarizer())
        assert first.movies_added == 1
        assert session.scalar(select(func.count()).select_from(Movie)) == 1
        assert session.scalar(select(func.count()).select_from(Rating)) == 2
        assert find_movie(session, ids={"movielens": "2"}) is find_movie(
            session, ids={"movielens": "1"}
        )
        snapshot = _snapshot(session)
        second = import_movielens(session, tmp_path, MovieLensBinarizer())
        assert (second.movies_added, second.users_added, second.ratings_added) == (0, 0, 0)
        assert _snapshot(session) == snapshot


def test_import_after_merge_does_not_recreate_dropped_duplicate(tmp_path):
    (tmp_path / "movies.csv").write_text(
        "movieId,title,genres\n1,Heat (1995),Crime\n2,Heat (1995),Crime\n", encoding="utf-8"
    )
    (tmp_path / "links.csv").write_text("movieId,imdbId,tmdbId\n1,,\n2,,\n", encoding="utf-8")
    (tmp_path / "ratings.csv").write_text("userId,movieId,rating,timestamp\n", encoding="utf-8")
    with _session() as session:
        import_movielens(session, tmp_path, MovieLensBinarizer())
        keep = find_movie(session, ids={"movielens": "1"})
        drop = find_movie(session, ids={"movielens": "2"})
        merge_movies(session, keep.id, drop.id)
        session.commit()
        stats = import_movielens(session, tmp_path, MovieLensBinarizer())
        assert stats.movies_added == 0
        assert session.scalar(select(func.count()).select_from(Movie)) == 1


def test_import_merges_movie_when_tmdb_pair_owner_differs(tmp_path):
    (tmp_path / "movies.csv").write_text(
        "movieId,title,genres\n5,Heat (1995),Crime\n", encoding="utf-8"
    )
    (tmp_path / "ratings.csv").write_text(
        "userId,movieId,rating,timestamp\n10,5,5.0,1\n", encoding="utf-8"
    )
    (tmp_path / "links.csv").write_text("movieId,imdbId,tmdbId\n5,,\n", encoding="utf-8")
    with _session() as session:
        import_movielens(session, tmp_path, MovieLensBinarizer())
        tmdb_movie = Movie(title="Heat", tmdb_type="movie", tmdb_id=862)
        session.add(tmdb_movie)
        session.commit()
        keep_id = tmdb_movie.id
        (tmp_path / "links.csv").write_text("movieId,imdbId,tmdbId\n5,,862\n", encoding="utf-8")
        stats = import_movielens(session, tmp_path, MovieLensBinarizer())
        assert stats.movies_merged == 1
        assert stats.movies_added == 0
        assert session.scalar(select(func.count()).select_from(Movie)) == 1
        assert find_movie(session, ids={"movielens": "5"}).id == keep_id
        assert find_movie(session, tmdb=("movie", 862)).id == keep_id
        assert session.scalar(select(Rating.movie_id)) == keep_id
        snapshot = _snapshot(session)
        again = import_movielens(session, tmp_path, MovieLensBinarizer())
        assert (again.movies_merged, again.movies_added, again.ratings_added) == (0, 0, 0)
        assert _snapshot(session) == snapshot


def _write_many_users(path, users: int, per_user: int):
    (path / "movies.csv").write_text(
        "movieId,title,genres\n" + "".join(f"{m},Film {m} (2000),Drama\n" for m in range(1, 6)),
        encoding="utf-8",
    )
    (path / "links.csv").write_text(
        "movieId,imdbId,tmdbId\n" + "".join(f"{m},{m},{100 + m}\n" for m in range(1, 6)),
        encoding="utf-8",
    )
    lines = ["userId,movieId,rating,timestamp"]
    for u in range(1, users + 1):
        lines += [f"{u},{m},5.0,1" for m in range(1, per_user + 1)]
    (path / "ratings.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_existing_user_is_skipped_with_all_ratings(tmp_path):
    data = _write_dataset(tmp_path)
    with _session() as session:
        session.add(User(external_movielens_id=10, is_synthetic=True, pool="world"))
        session.commit()
        stats = import_movielens(session, data, MovieLensBinarizer())
        assert (stats.users_added, stats.ratings_added) == (1, 1)
        user = session.scalar(select(User).where(User.external_movielens_id == 10))
        assert session.scalar(select(func.count()).where(Rating.user_id == user.id)) == 0


def test_ratings_are_written_in_batches(tmp_path, monkeypatch):
    monkeypatch.setattr("cinemate.db.importer.BATCH_SIZE", 7)
    data = _write_many_users(tmp_path, users=6, per_user=5)
    with _session() as session:
        executed = []
        original = session.execute

        def spy(statement, params=None, *a, **kw):
            if isinstance(params, list) and getattr(statement, "is_insert", False):
                executed.append(len(params))
            return original(statement, params, *a, **kw)

        monkeypatch.setattr(session, "execute", spy)
        stats = import_movielens(session, data, MovieLensBinarizer())
        assert stats.ratings_added == 30
        assert executed == [7, 7, 7, 7, 2]
        assert session.scalar(select(func.count()).select_from(Rating)) == 30


def test_user_selection_and_progress(tmp_path, monkeypatch):
    monkeypatch.setattr("cinemate.db.importer.PROGRESS_EVERY", 10)
    data = _write_many_users(tmp_path, users=8, per_user=5)
    with (data / "ratings.csv").open("a", encoding="utf-8") as f:
        f.write("99,1,5.0,1\n")  # a user below the threshold
    reads: list[int] = []
    with _session() as session:
        stats = import_movielens(
            session,
            data,
            MovieLensBinarizer(),
            min_user_ratings=3,
            max_users=4,
            seed=3,
            progress=reads.append,
        )
        assert (stats.users_added, stats.ratings_added) == (4, 20)
        ext = set(session.scalars(select(User.external_movielens_id)))
        assert len(ext) == 4 and 99 not in ext
        again = import_movielens(
            session, data, MovieLensBinarizer(), min_user_ratings=3, max_users=4, seed=3
        )
        assert (again.users_added, again.ratings_added) == (0, 0)
    assert reads == [10, 20]


def test_movies_with_same_tmdb_pair_share_one_movie_and_one_rating(tmp_path):
    data = _write_dataset(tmp_path)
    (data / "movies.csv").write_text(
        "movieId,title,genres\n1,Toy Story (1995),Animation\n3,Toy Story (1995),Animation\n",
        encoding="utf-8",
    )
    (data / "links.csv").write_text("movieId,imdbId,tmdbId\n1,1,862\n3,1,862\n", encoding="utf-8")
    (data / "ratings.csv").write_text(
        "userId,movieId,rating,timestamp\n10,1,5.0,1\n10,3,5.0,2\n", encoding="utf-8"
    )
    with _session() as session:
        stats = import_movielens(session, data, MovieLensBinarizer())
        assert stats.movies_added == 1
        assert stats.ratings_added == 1
        assert session.scalar(select(func.count()).select_from(Rating)) == 1


def test_cli_import_ml_32m_selection(tmp_path, monkeypatch, capsys):
    data = _write_many_users(tmp_path, users=6, per_user=5)
    seen = {}

    def fake_ensure(d, name="ml-latest-small"):
        seen["name"] = name
        return d

    monkeypatch.setattr("cinemate.cli.ensure_movielens", fake_ensure)
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    args = ["import-movielens", "--database-url", url, "--data-dir", str(data)]
    args += ["--dataset", "ml-32m", "--min-user-ratings", "5", "--max-users", "3"]
    assert main(args) == 0
    assert seen["name"] == "ml-32m"
    assert "users added: 3" in capsys.readouterr().out
    assert main(args) == 0
    assert "users added: 0" in capsys.readouterr().out
