from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.binarize import RelativeMeanBinarizer
from cinemate.cli import main
from cinemate.db.catalog import link
from cinemate.db.models import Movie, Rating, User
from cinemate.db.ratings_import import import_ratings_csv, normalize_title
from cinemate.db.session import create_all, make_engine
from cinemate.ratings_csv import load_ratings

HEADER = "user_id,movie_id,title_ru,title_original,type,year,genres,kp_rating,user_rating\n"


def _session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return Session(engine)


def _write(tmp_path, body):
    path = tmp_path / "ratings.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def _binarizer(path, types=None, threshold=0.5):
    return RelativeMeanBinarizer.fit(load_ratings(path, types), threshold=threshold)


def _user_rows(user_id, scores, first_movie=1000):
    """20+ ratings for one user: ``scores`` for movies ``first_movie``, ``first_movie + 1``..."""
    return "".join(
        f"{user_id},{first_movie + i},Фильм {first_movie + i},Film {first_movie + i},Film,2000,"
        f"драма,,{s}\n"
        for i, s in enumerate(scores)
    )


def _run(session, path, types=None, threshold=0.5):
    return import_ratings_csv(session, path, _binarizer(path, types, threshold), types)


def _movielens_movie(session, title="Heat", year=1995, **kw):
    movie = Movie(title=title, year=year, genres=["Crime"], external_movielens_id=6, **kw)
    session.add(movie)
    session.commit()
    return movie


def _enough(user_id=1, first_movie=1000):
    # mean 5.5: scores 10 -> like, 1 -> dislike, 5/6 -> discarded
    return _user_rows(user_id, [10] * 10 + [1] * 10, first_movie)


def test_normalize_title():
    assert normalize_title("  Heat:  The   Movie! ") == "heat the movie"
    assert normalize_title("WALL·E") == "wall e"


def test_merge_with_movielens_by_title_and_year(tmp_path):
    session = _session()
    movie = _movielens_movie(session, title="The Heat")
    body = "1,77,Жара,the HEAT,Film,1995,драма,,10\n" + _enough(1, 2000)
    stats = _run(session, _write(tmp_path, body))
    assert stats.movies_merged == 1
    assert stats.movies_added == 20
    session.refresh(movie)
    assert movie.title == "The Heat"
    assert movie.external_ratings_id == 77
    assert session.scalar(select(Rating.value).where(Rating.movie_id == movie.id)) is not None


def test_merge_with_original_title_of_existing_movie(tmp_path):
    session = _session()
    movie = _movielens_movie(session, title="Жара", original_title="Heat")
    stats = _run(session, _write(tmp_path, "1,77,,Heat,Film,1995,,,10\n"))
    assert stats.movies_merged == 1
    session.refresh(movie)
    assert movie.external_ratings_id == 77


def test_different_year_is_not_merged(tmp_path):
    session = _session()
    movie = _movielens_movie(session)
    stats = _run(session, _write(tmp_path, "1,77,,Heat,Film,1996,,,10\n"))
    assert (stats.movies_merged, stats.movies_added, stats.movies_ambiguous) == (0, 1, 0)
    session.refresh(movie)
    assert movie.external_ratings_id is None


def test_no_original_title_or_year_creates_new_movie(tmp_path):
    session = _session()
    _movielens_movie(session)
    body = "1,77,Жара,,Film,1995,,,10\n1,78,,Heat,Film,,,,10\n"
    stats = _run(session, _write(tmp_path, body))
    assert (stats.movies_merged, stats.movies_added) == (0, 2)


def test_two_candidates_are_ambiguous(tmp_path):
    session = _session()
    session.add_all(
        [
            Movie(title="Heat", year=1995, external_movielens_id=1),
            Movie(title="Heat!", year=1995, external_movielens_id=2),
        ]
    )
    session.commit()
    stats = _run(session, _write(tmp_path, "1,77,Жара,Heat,Film,1995,,,10\n"))
    assert (stats.movies_merged, stats.movies_added, stats.movies_ambiguous) == (0, 1, 1)
    assert session.scalars(select(Movie.external_ratings_id)).all().count(77) == 1


def test_second_csv_movie_for_same_candidate_is_ambiguous(tmp_path):
    session = _session()
    _movielens_movie(session)
    body = "1,77,Жара,Heat,Film,1995,,,10\n1,78,Жара 2,Heat,Film,1995,,,10\n"
    stats = _run(session, _write(tmp_path, body))
    assert (stats.movies_merged, stats.movies_added, stats.movies_ambiguous) == (1, 1, 1)


def test_new_movie_fields(tmp_path):
    session = _session()
    _run(session, _write(tmp_path, '1,5,Жара,Heat,Film,1995,"драма, криминал",,10\n'))
    movie = session.scalars(select(Movie)).one()
    assert (movie.title, movie.original_title, movie.year) == ("Жара", "Heat", 1995)
    assert movie.genres == ["драма", "криминал"]
    assert movie.external_ratings_id == 5
    assert movie.tmdb_id is None


def test_title_falls_back_to_original_and_skips_without_any(tmp_path):
    session = _session()
    body = "1,5,,Heat,Film,1995,,,10\n1,6,,,Film,1996,,,10\n"
    stats = _run(session, _write(tmp_path, body))
    assert (stats.movies_added, stats.movies_skipped_no_title) == (1, 1)
    assert session.scalars(select(Movie.title)).all() == ["Heat"]


def test_existing_external_movie_only_fills_empty_fields(tmp_path):
    session = _session()
    keep = Movie(title="Keep", external_ratings_id=5, year=2000, genres=[])
    session.add(keep)
    link(session, keep, "ratings_csv", 5)
    session.commit()
    _run(session, _write(tmp_path, '1,5,Other,Heat,Film,1995,"драма",,10\n'))
    movie = session.scalars(select(Movie)).one()
    assert (movie.title, movie.year, movie.original_title) == ("Keep", 2000, "Heat")
    assert movie.genres == ["драма"]


def test_types_filter(tmp_path):
    session = _session()
    body = "1,5,Один,One,Film,2000,,,10\n1,6,Два,Two,MiniSeries,2001,,,10\n"
    stats = _run(session, _write(tmp_path, body), types=["film"])
    assert stats.movies_added == 1
    assert session.scalars(select(Movie.title)).all() == ["Один"]


def test_rating_signs_and_no_raw_scores(tmp_path):
    session = _session()
    path = _write(tmp_path, _enough())
    stats = _run(session, path)
    assert (stats.users_added, stats.ratings_added, stats.ratings_skipped) == (1, 20, 0)
    values = session.scalars(select(Rating.value)).all()
    assert sorted(set(values)) == [-1, 1]
    assert values.count(1) == 10
    user = session.scalars(select(User)).one()
    assert user.external_ratings_id == 1
    assert user.is_synthetic is True
    assert user.email is None and user.session_token is None


def test_discarded_ratings_are_skipped(tmp_path):
    session = _session()
    path = _write(tmp_path, _user_rows(1, [10] * 9 + [5, 6] + [1] * 9))
    stats = _run(session, path, threshold=1.0)
    assert (stats.ratings_added, stats.ratings_skipped) == (18, 2)


def test_users_with_few_ratings_get_no_ratings(tmp_path):
    session = _session()
    body = _enough(1) + _user_rows(2, [10, 1, 10])
    stats = _run(session, _write(tmp_path, body))
    assert stats.users_added == 1
    assert stats.ratings_added == 20
    assert stats.ratings_skipped == 3
    assert session.scalars(select(User.external_ratings_id)).all() == [1]


def test_second_import_changes_nothing(tmp_path):
    session = _session()
    _movielens_movie(session)
    path = _write(tmp_path, "9,77,Жара,Heat,Film,1995,,,10\n" + _enough())

    def snapshot():
        return (
            session.execute(select(Movie.id, Movie.title, Movie.external_ratings_id)).all(),
            session.execute(select(User.id, User.external_ratings_id)).all(),
            session.execute(select(Rating.user_id, Rating.movie_id, Rating.value)).all(),
        )

    _run(session, path)
    before = snapshot()
    stats = _run(session, path)
    assert snapshot() == before
    assert (
        stats.movies_merged,
        stats.movies_added,
        stats.users_added,
        stats.ratings_added,
        stats.popularity_updated,
    ) == (0, 0, 0, 0, 0)


def test_existing_rating_pair_is_not_changed(tmp_path):
    session = _session()
    path = _write(tmp_path, _enough())
    _run(session, path)
    rating = session.scalars(select(Rating).order_by(Rating.id)).first()
    original = rating.value
    rating.value = -original
    session.commit()
    stats = _run(session, path)
    assert stats.ratings_added == 0
    session.refresh(rating)
    assert rating.value == -original


def test_popularity_is_recomputed(tmp_path):
    session = _session()
    body = _enough(1) + _enough(2) + _enough(3)
    stats = _run(session, _write(tmp_path, body))
    assert stats.popularity_updated == 20
    scores = dict(session.execute(select(Movie.external_ratings_id, Movie.popularity_score)).all())
    assert scores[1000] == 3.0  # liked by all three
    assert scores[1019] == 0.0  # disliked by all three


def test_cli_import_ratings_csv(tmp_path, capsys):
    path = _write(tmp_path, _enough())
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    args = ["import-ratings-csv", "--file", str(path), "--database-url", url]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "movies added: 20" in out and "ratings added: 20" in out and "users added: 1" in out
    assert main(args) == 0
    assert "ratings added: 0" in capsys.readouterr().out


def test_cli_missing_file_exits_2(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    args = ["import-ratings-csv", "--file", str(tmp_path / "nope.csv"), "--database-url", url]
    assert main(args) == 2
    assert "cannot read" in capsys.readouterr().err


def test_cli_types_and_threshold(tmp_path, capsys):
    path = _write(tmp_path, _enough())
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    base = ["import-ratings-csv", "--file", str(path), "--database-url", url]
    assert main([*base, "--rel-threshold", "0"]) == 2
    assert "--rel-threshold" in capsys.readouterr().err
    assert main([*base, "--types", "Series"]) == 2
    assert "no ratings" in capsys.readouterr().err
    assert main([*base, "--types", "Film", "--rel-threshold", "6"]) == 0
    assert "ratings added: 0" in capsys.readouterr().out
