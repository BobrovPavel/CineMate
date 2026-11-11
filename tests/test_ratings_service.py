import pytest
from sqlalchemy.orm import Session

from cinemate.db.catalog import merge_movies
from cinemate.db.models import ExternalRating, Movie, MovieExternalId, Rating, User
from cinemate.db.session import create_all, make_engine
from cinemate.services.ratings import CINEMATE_MIN_RATINGS, RatingOut, movie_ratings


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with Session(engine) as s:
        yield s


def _movie(session, **kw):
    movie = Movie(title="Heat", tmdb_type="movie", tmdb_id=949, **kw)
    session.add(movie)
    session.flush()
    return movie


def _rate(session, movie, likes, dislikes, pool="world"):
    for i in range(likes + dislikes):
        user = User(pool=pool)
        session.add(user)
        session.flush()
        session.add(Rating(user_id=user.id, movie_id=movie.id, value=1 if i < likes else -1))
    session.flush()


def _full(session):
    movie = _movie(session, tmdb_vote_average=7.9, tmdb_vote_count=5000, imdb_id="tt0113277")
    session.add(MovieExternalId(source="imdb", external_id="tt0113277", movie_id=movie.id))
    session.add(ExternalRating(movie_id=movie.id, source="imdb", value=8.3, votes=700000))
    session.add(ExternalRating(movie_id=movie.id, source="kinopoisk", value=8.0))
    _rate(session, movie, 8, 2)
    session.flush()
    return movie


def test_en_default_hides_kinopoisk_and_orders_imdb_tmdb_cinemate(session, monkeypatch):
    monkeypatch.delenv("SHOW_KINOPOISK_RATING", raising=False)
    movie = _full(session)
    assert movie_ratings(session, movie, "world", "en") == [
        RatingOut("imdb", "IMDb", 8.3, "10", 700000, "https://www.imdb.com/title/tt0113277/"),
        RatingOut("tmdb", "TMDB", 7.9, "10", 5000, "https://www.themoviedb.org/movie/949"),
        RatingOut("cinemate", "CineMate", 80.0, "%", 10, None),
    ]


@pytest.mark.parametrize(
    ("env", "language", "shown"),
    [
        (None, "ru", True),
        (None, "en", False),
        ("ru", "ru", True),
        ("ru", "en", False),
        ("all", "en", True),
        ("all", "ru", True),
        ("off", "ru", False),
        ("off", "en", False),
        ("1", "en", True),
        ("0", "ru", False),
        ("garbage", "ru", True),
        ("garbage", "en", False),
    ],
)
def test_kinopoisk_display_rule(session, monkeypatch, env, language, shown):
    if env is None:
        monkeypatch.delenv("SHOW_KINOPOISK_RATING", raising=False)
    else:
        monkeypatch.setenv("SHOW_KINOPOISK_RATING", env)
    movie = _full(session)
    sources = [r.source for r in movie_ratings(session, movie, "world", language)]
    assert ("kinopoisk" in sources) is shown


def test_ru_order_kinopoisk_first_with_link_and_votes(session, monkeypatch):
    monkeypatch.delenv("SHOW_KINOPOISK_RATING", raising=False)
    movie = _full(session)
    session.add(MovieExternalId(source="kinopoisk", external_id="448", movie_id=movie.id))
    kp = session.get(ExternalRating, (movie.id, "kinopoisk"))
    kp.votes = 12345
    session.flush()
    ratings = movie_ratings(session, movie, "world", "ru")
    assert [r.source for r in ratings] == ["kinopoisk", "imdb", "tmdb", "cinemate"]
    assert ratings[0] == RatingOut(
        "kinopoisk", "Кинопоиск", 8.0, "10", 12345, "https://www.kinopoisk.ru/film/448/"
    )


def test_kinopoisk_without_id_or_votes(session, monkeypatch):
    monkeypatch.delenv("SHOW_KINOPOISK_RATING", raising=False)
    movie = _full(session)
    first = movie_ratings(session, movie, "world", "ru")[0]
    assert (first.source, first.votes, first.url) == ("kinopoisk", None, None)


def test_cinemate_rating_needs_ten_ratings(session):
    movie = _movie(session)
    _rate(session, movie, CINEMATE_MIN_RATINGS - 1, 0)
    assert movie_ratings(session, movie, "world", "en") == []
    _rate(session, movie, 0, 1)
    (own,) = movie_ratings(session, movie, "world", "en")
    assert (own.source, own.value, own.votes) == ("cinemate", 90.0, 10)


def test_cinemate_rating_counts_only_the_pool(session):
    movie = _movie(session)
    _rate(session, movie, 10, 0, pool="world")
    _rate(session, movie, 0, 10, pool="ru")
    assert movie_ratings(session, movie, "world", "en")[0].value == 100.0
    assert movie_ratings(session, movie, "ru", "ru")[0].value == 0.0


def test_missing_sources_are_skipped(session):
    movie = Movie(title="Unknown")
    session.add(movie)
    session.flush()
    assert movie_ratings(session, movie, "world", "en") == []
    zero = _movie(session, tmdb_vote_average=0.0, tmdb_vote_count=0)
    assert movie_ratings(session, zero, "world", "en") == []


def test_merge_keeps_external_ratings(session):
    keep = Movie(title="Keep")
    drop = Movie(title="Drop")
    session.add_all([keep, drop])
    session.flush()
    session.add(ExternalRating(movie_id=keep.id, source="imdb", value=7.0, votes=1))
    session.add(ExternalRating(movie_id=drop.id, source="imdb", value=9.0, votes=2))
    session.add(ExternalRating(movie_id=drop.id, source="kinopoisk", value=6.5))
    session.flush()
    merge_movies(session, keep_id=keep.id, drop_id=drop.id)
    rows = {r.source: (r.value, r.votes) for r in session.query(ExternalRating)}
    assert rows == {"imdb": (7.0, 1), "kinopoisk": (6.5, None)}
