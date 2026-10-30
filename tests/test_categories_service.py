import pytest
from sqlalchemy.orm import sessionmaker

from cinemate.config import RecommenderSettings
from cinemate.db.features import seed_genres
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Rating, User, UserCategoryPref
from cinemate.db.session import create_all, make_engine
from cinemate.services.categories import get_category_prefs, set_category_pref
from cinemate.services.recommendations import get_recommendations
from tests.category_fixtures import CF, MARVEL, MARVEL_CANDIDATES, OTHER, seed


@pytest.fixture
def factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    seed_genres(engine)
    return sessionmaker(engine)


def settings(**changes):
    return RecommenderSettings(**{**CF, **changes})


def feed(factory, **changes):
    with factory() as s:
        result = get_recommendations(
            s, MatrixStore(factory), s.get(User, 1), limit=40, settings=settings(**changes)
        )
    assert result.strategy == "collaborative"
    return [i.movie.id for i in result.items]


def prefs(factory, language="en", **changes):
    with factory() as s:
        return get_category_prefs(
            s, MatrixStore(factory), s.get(User, 1), settings=settings(**changes), language=language
        )


def build(factory, **kwargs):
    with factory() as s:
        seed(s, **kwargs)
        s.commit()


def test_without_the_rule_category_candidates_come_first(factory):
    build(factory, dislikes=2)
    ids = feed(factory)
    assert set(ids[:6]) == set(MARVEL_CANDIDATES + MARVEL[2:])


def test_studio_rule_moves_candidates_after_position_20(factory):
    build(factory, dislikes=3, company=True)  # 3 dislikes, no likes: the studio triggers
    ids = feed(factory)
    category = set(MARVEL_CANDIDATES + MARVEL[3:])
    assert not category & set(ids[:20])
    assert set(ids[:20]) == set(OTHER)
    assert ids[20:] == [m for m in sorted(category)]  # kept their order, none dropped


def test_below_threshold_does_not_trigger(factory):
    build(factory, dislikes=2)
    assert not set(feed(factory)[:3]) - set(MARVEL_CANDIDATES + MARVEL[2:])
    assert prefs(factory) == []


def test_a_like_in_the_category_cancels_the_rule(factory):
    build(factory, dislikes=4, target_likes=[MARVEL[4]])
    ids = feed(factory)
    assert set(ids[:3]) <= set(MARVEL_CANDIDATES)
    assert prefs(factory) == []


def test_big_studio_is_not_recognisable(factory):
    # the studio has 8 rated movies in the pool: recognisable only with a limit of 8 or more
    build(factory, dislikes=3, company=True)
    kwargs = dict(hide_dislikes_genre=99)
    assert set(feed(factory, hide_studio_max_movies=7, **kwargs)[:5]) == set(
        MARVEL_CANDIDATES + MARVEL[3:]
    )
    assert not set(MARVEL_CANDIDATES) & set(feed(factory, hide_studio_max_movies=8, **kwargs)[:20])


def test_collection_triggers_with_three_dislikes(factory):
    build(factory, dislikes=3, company=False, collection=True)
    kwargs = dict(hide_dislikes_genre=99)
    ids = feed(factory, **kwargs)
    assert not set(MARVEL_CANDIDATES) & set(ids[:20])
    [view] = prefs(factory, **kwargs)
    assert (view.kind, view.name, view.disliked, view.rated) == (
        "collection",
        "Avengers Collection",
        3,
        3,
    )


def test_genre_needs_five_dislikes_and_is_named_in_the_language(factory):
    only_genre = dict(hide_dislikes_studio=99, hide_dislikes_collection=99, hide_dislikes_anime=99)
    build(factory, dislikes=4, company=False)
    assert prefs(factory, **only_genre) == []
    with factory() as s:
        s.add(Rating(user_id=1, movie_id=MARVEL[4], value=-1))
        s.commit()
    [view] = prefs(factory, language="ru", **only_genre)
    assert (view.kind, view.key, view.name, view.disliked, view.rated, view.show) == (
        "genre",
        "28",
        "боевик",
        5,
        5,
        False,
    )
    assert prefs(factory, language="en", **only_genre)[0].name == "Action"


def test_counts_n_of_n_and_names(factory):
    build(factory, dislikes=5, company=True)
    views = {(v.kind, v.key): v for v in prefs(factory)}
    studio = views[("studio", "1")]
    assert (studio.name, studio.disliked, studio.rated, studio.show) == (
        "Marvel Studios",
        5,
        5,
        False,
    )
    assert ("genre", "28") in views


def test_override_restores_places_and_removing_it_restores_the_rule(factory):
    build(factory, dislikes=5, target_likes=OTHER[:2])
    ids = feed(factory)
    assert max(ids.index(m) for m in OTHER[2:]) < min(ids.index(m) for m in MARVEL_CANDIDATES)

    with factory() as s:
        for kind, key in (("studio", "1"), ("genre", "28")):
            set_category_pref(s, s.get(User, 1), kind, key, True)
        s.commit()
    assert set(feed(factory)[:3]) == set(MARVEL_CANDIDATES)
    shown = {(v.kind, v.key): v for v in prefs(factory)}
    assert shown[("studio", "1")].show is True
    assert shown[("studio", "1")].disliked == 5

    # new dislikes do not cancel the override
    with factory() as s:
        s.add_all([Rating(user_id=1, movie_id=m, value=-1) for m in MARVEL_CANDIDATES[:1]])
        s.commit()
    assert prefs(factory)[0].show is True

    with factory() as s:
        for kind, key in (("studio", "1"), ("genre", "28")):
            set_category_pref(s, s.get(User, 1), kind, key, False)
        s.commit()
        assert s.query(UserCategoryPref).count() == 0
    ids = feed(factory)
    assert max(ids.index(m) for m in OTHER[2:]) < min(ids.index(m) for m in MARVEL_CANDIDATES[1:])


def test_set_pref_is_idempotent_and_validates_kind(factory):
    build(factory, dislikes=0)
    with factory() as s:
        user = s.get(User, 1)
        set_category_pref(s, user, "studio", "1", True)
        set_category_pref(s, user, "studio", "1", True)
        set_category_pref(s, user, "studio", "2", False)
        assert s.query(UserCategoryPref).count() == 1
        with pytest.raises(ValueError):
            set_category_pref(s, user, "actor", "1", True)


def penalty_feed(factory, **changes):
    """A (10) and B (11) tie on CF; A is liked by the same users as the disliked movie D (12)."""
    with factory() as s:
        s.add_all([User(id=i) for i in range(1, 9)])
        from cinemate.db.models import Movie

        s.add_all([Movie(id=i, title=f"m{i}", tmdb_type="movie") for i in (1, 2, 10, 11, 12)])
        s.flush()
        for u in range(1, 9):
            for m in (1, 2):
                s.add(Rating(user_id=u, movie_id=m, value=1))
        for u in range(2, 6):
            s.add_all(
                [Rating(user_id=u, movie_id=10, value=1), Rating(user_id=u, movie_id=12, value=1)]
            )
        for u in range(5, 9):
            s.add(Rating(user_id=u, movie_id=11, value=1))
        s.add(Rating(user_id=1, movie_id=12, value=-1))
        s.commit()
    with factory() as s:
        result = get_recommendations(
            s, MatrixStore(factory), s.get(User, 1), limit=10, settings=settings(**changes)
        )
    return [i.movie.id for i in result.items]


def test_similarity_penalty_applies_from_the_ratings_threshold(factory):
    # user 1 has 3 ratings
    assert penalty_feed(factory, dislike_item_min_ratings=4) == [10, 11]


def test_similarity_penalty_pushes_down_movies_like_the_disliked(factory):
    assert penalty_feed(factory, dislike_item_min_ratings=3) == [11, 10]


def test_similarity_penalty_off_with_zero_weight(factory):
    assert penalty_feed(factory, dislike_item_min_ratings=3, dislike_item_weight=0.0) == [10, 11]
