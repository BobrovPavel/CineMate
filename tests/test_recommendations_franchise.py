import pytest
from sqlalchemy.orm import sessionmaker

from cinemate.config import RecommenderSettings
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Collection, Movie, Rating, SeenMark, User
from cinemate.db.session import create_all, make_engine
from cinemate.services.recommendations import get_recommendations

SETTINGS = RecommenderSettings(
    k=150,
    lam=1.0,
    min_overlap=1,
    pop_penalty=0.0,
    min_user_ratings=2,
    taste_weight=0.0,
    sim_power=1.0,
    shrink="count",
)
PARTS = [21, 22, 23, 24, 25]  # collection 1, years 2001..2005
PLAIN = [30, 31, 32, 33]


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return sessionmaker(engine)


def seed(factory, part_likers=None, user_ratings=()):
    """User 1 likes 1..6; users 2..8 like 1..6, every part and the plain movies 30..33.

    ``part_likers`` maps a part id to the number of neighbours liking it (default 7)."""
    part_likers = part_likers or {}
    with factory() as s:
        s.add(Collection(id=1, name="Saga"))
        s.add_all([Movie(id=i, title=f"m{i}") for i in [*range(1, 7), *PLAIN]])
        s.add_all(
            Movie(id=m, title=f"p{m}", year=2001 + i, collection_id=1) for i, m in enumerate(PARTS)
        )
        s.add_all([User(id=i) for i in range(1, 9)])
        s.flush()
        for u in range(1, 9):
            for m in range(1, 7):
                s.add(Rating(user_id=u, movie_id=m, value=1))
        for u in range(2, 9):
            for m in PLAIN:
                if u <= 4:
                    s.add(Rating(user_id=u, movie_id=m, value=1))
            for m in PARTS:
                if u - 1 <= part_likers.get(m, 7):
                    s.add(Rating(user_id=u, movie_id=m, value=1))
        for m, v in user_ratings:
            s.add(Rating(user_id=1, movie_id=m, value=v))
        s.commit()


def recommend(factory, **kw):
    with factory() as s:
        return get_recommendations(
            s, MatrixStore(factory), s.get(User, 1), settings=SETTINGS, limit=20, **kw
        )


def franchise_items(result):
    return [i for i in result.items if i.movie.id in PARTS]


def test_at_most_one_part_and_first_for_unfamiliar_franchise(factory):
    seed(factory)
    items = franchise_items(recommend(factory))
    assert [i.movie.id for i in items] == [21]
    card = items[0].collection
    assert (card.id, card.name, card.parts, card.unseen, card.mode) == (1, "Saga", 5, 5, "first")


def test_next_part_after_liked_ones(factory):
    seed(factory, user_ratings=[(21, 1), (22, 1)])
    (item,) = franchise_items(recommend(factory))
    assert item.movie.id == 23
    assert item.collection.mode == "next"
    assert item.collection.rated_parts == (1, 2)
    assert item.collection.unseen == 3


def test_marks_count_as_seen_for_the_next_part(factory):
    seed(factory, user_ratings=[(21, 1)])
    with factory() as s:
        s.add(SeenMark(user_id=1, movie_id=22, type="watched"))
        s.commit()
    (item,) = franchise_items(recommend(factory))
    assert item.movie.id == 23
    assert item.collection.rated_parts == (1, 2)


def test_fully_rated_franchise_is_not_shown(factory):
    seed(factory, user_ratings=[(m, 1) for m in PARTS])
    result = recommend(factory)
    assert franchise_items(result) == []
    assert {i.movie.id for i in result.items} == set(PLAIN)


def test_movies_without_collection_are_untouched(factory):
    seed(factory)
    result = recommend(factory)
    assert {i.movie.id for i in result.items} >= set(PLAIN)
    assert all(i.collection is None for i in result.items if i.movie.id in PLAIN)


def test_representative_takes_the_place_of_the_best_part(factory):
    # part 25 is liked by everyone, the first part only by 3 neighbours, plain movies by 3
    seed(factory, part_likers={21: 3, 22: 3, 23: 3, 24: 3, 25: 7})
    result = recommend(factory)
    ids = [i.movie.id for i in result.items]
    assert ids[0] == 21  # first part, standing where 25 (the best scored part) stood
    best = max(result.items, key=lambda i: i.score)
    assert result.items[0].score == best.score


def test_hidden_collection_is_demoted_as_a_whole(factory):
    seed(factory, user_ratings=[(21, -1), (22, -1), (23, -1)])
    result = recommend(factory)
    ids = [i.movie.id for i in result.items]
    assert ids.count(24) + ids.count(25) == 1
    assert ids[-1] in (24, 25)  # hidden category goes below every ordinary movie
    assert set(PLAIN) <= set(ids[:-1])
