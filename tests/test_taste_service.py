import pytest
from sqlalchemy.orm import sessionmaker

from cinemate.config import RecommenderSettings
from cinemate.db.features import seed_genres
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Collection, Movie, MovieGenre, Rating, SeenMark, User
from cinemate.db.session import create_all, make_engine
from cinemate.services.recommendations import get_recommendations

FANTASY, DRAMA, ANIMATION = 14, 18, 16
# lam=1 and no popularity penalty: more neighbours who liked a movie = a higher CF score
CF = dict(k=150, lam=1.0, min_overlap=1, pop_penalty=0.0, min_user_ratings=2)


def _settings(**changes) -> RecommenderSettings:
    return RecommenderSettings(**{**CF, **changes})


def build(factory, groups, user_likes=6):
    """Movies 1..6 are fantasy films the target (user 1) likes; users 2..8 like them too.

    ``groups`` maps a genre id to the list of candidate movie ids: all 7 neighbours like the
    first group's movies, only 3 of them like every other group's movies.
    """
    seed_genres(factory.kw["bind"])
    with factory() as s:
        s.add_all([Movie(id=i, title=f"m{i}", tmdb_type="movie") for i in range(1, 7)])
        s.add_all([MovieGenre(movie_id=i, genre_id=FANTASY) for i in range(1, 7)])
        s.add_all([User(id=i) for i in range(1, 9)])
        s.flush()
        for u in range(1, 9):
            for m in range(1, 7 if u > 1 else user_likes + 1):
                s.add(Rating(user_id=u, movie_id=m, value=1))
        for position, (genre, ids) in enumerate(groups.items()):
            for m in ids:
                s.add(Movie(id=m, title=f"m{m}", tmdb_type="movie"))
                s.add(MovieGenre(movie_id=m, genre_id=genre))
                for u in range(2, 9 if position == 0 else 5):
                    s.add(Rating(user_id=u, movie_id=m, value=1))
        s.commit()


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return sessionmaker(engine)


def _ids(factory, settings, limit=20, language="en"):
    with factory() as s:
        result = get_recommendations(
            s, MatrixStore(factory), s.get(User, 1), limit=limit, settings=settings,
            language=language,
        )  # fmt: skip
    assert result.strategy == "collaborative"
    return result


def test_fantasy_lover_gets_fantasy_up(factory):
    build(factory, {DRAMA: [10, 11, 12], FANTASY: [20, 21, 22]})
    off = [i.movie.id for i in _ids(factory, _settings(taste_weight=0)).items]
    on = [i.movie.id for i in _ids(factory, _settings(taste_weight=2)).items]
    assert off == [10, 11, 12, 20, 21, 22]
    assert on[:3] == [20, 21, 22]


def test_only_movies_liker_gets_animation_down(factory):
    # drama and animation have the same CF score; the user liked only drama-less fantasy films
    build(factory, {ANIMATION: [10, 11, 12], FANTASY: [20, 21, 22]})
    on = [i.movie.id for i in _ids(factory, _settings(taste_weight=2)).items]
    assert on[-3:] == [10, 11, 12]


def test_zero_weight_keeps_the_cf_order_and_drops_taste_fields(factory):
    build(factory, {DRAMA: [10, 11, 12], FANTASY: [20, 21, 22]})
    result = _ids(factory, _settings(taste_weight=0))
    assert [i.movie.id for i in result.items] == [10, 11, 12, 20, 21, 22]
    assert all(i.because_taste is None for i in result.items)


def test_no_more_than_four_of_a_genre_in_ten(factory):
    # three genres: with two, ten places cannot satisfy a limit of four each
    build(factory, {FANTASY: list(range(20, 30)), DRAMA: list(range(10, 16)), 35: [30, 31, 32, 33]})
    ids = [i.movie.id for i in _ids(factory, _settings(taste_weight=2), limit=10).items]
    assert len(ids) == 10
    assert sum(1 for i in ids if 20 <= i < 30) <= 4
    assert sum(1 for i in ids if i < 20) <= 4
    assert sorted(ids) == sorted(set(ids))


def test_no_more_than_two_of_a_franchise_in_ten(factory):
    build(
        factory,
        {FANTASY: list(range(20, 30)), DRAMA: list(range(10, 20)), 35: list(range(30, 40))},
    )
    with factory() as s:
        s.add(Collection(id=1, name="Saga"))
        s.flush()
        for m in range(20, 26):
            s.get(Movie, m).collection_id = 1
        s.commit()
    ids = [i.movie.id for i in _ids(factory, _settings(taste_weight=2), limit=10).items]
    assert sum(1 for i in ids if 20 <= i < 26) <= 2


def test_reason_only_for_a_sure_feature(factory):
    build(factory, {DRAMA: [10, 11], FANTASY: [20, 21]})
    items = {i.movie.id: i for i in _ids(factory, _settings(taste_weight=2)).items}
    reason = items[20].because_taste
    assert (reason.kind, reason.id, reason.name) == ("genre", "14", "Fantasy")
    assert items[10].because_taste is None


def test_reason_name_follows_the_language(factory):
    build(factory, {DRAMA: [10, 11], FANTASY: [20, 21]})
    items = {i.movie.id: i for i in _ids(factory, _settings(taste_weight=2), language="ru").items}
    assert items[20].because_taste.name == "фэнтези"


def test_no_reason_with_fewer_than_three_likes(factory):
    build(factory, {DRAMA: [10, 11], FANTASY: [20, 21]}, user_likes=2)
    items = _ids(factory, _settings(taste_weight=2)).items
    assert all(i.because_taste is None for i in items)


def test_not_interested_marks_count_as_soft_dislikes(factory):
    build(factory, {DRAMA: [10, 11], FANTASY: [20, 21]})
    with factory() as s:
        s.add_all([Movie(id=40, title="x", tmdb_type="movie"), Movie(id=41, title="y")])
        s.add_all(
            [MovieGenre(movie_id=40, genre_id=DRAMA), Rating(user_id=2, movie_id=40, value=1)]
        )
        s.add(SeenMark(user_id=1, movie_id=40, type="not_interested"))
        s.commit()
    result = _ids(factory, _settings(taste_weight=2))
    assert 40 not in {i.movie.id for i in result.items}
