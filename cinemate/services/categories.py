"""Hidden categories: what the automatic rule lowered in the feed and the user's overrides.

No web framework is used here; writes only flush, the caller commits.
"""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.config import RecommenderSettings
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Collection, Company, Genre, Movie, Rating, User, UserCategoryPref
from cinemate.recommender.categories import (
    ANIME_KEY,
    ANIME_KIND,
    COLLECTION_KIND,
    GENRE_KIND,
    KINDS,
    STUDIO_KIND,
    CategoryKey,
    category_stats,
    column_categories,
    triggered_categories,
)
from cinemate.services.recommendations import with_fresh_row


@dataclass(frozen=True)
class CategoryView:
    """A category with the user's counts. ``show`` is ``False`` while the rule hides it and
    ``True`` once the user overrode the rule. ``disliked`` of ``rated`` is the "N of N"."""

    kind: str
    key: str
    name: str
    disliked: int
    rated: int
    show: bool


def set_category_pref(session: Session, user: User, kind: str, key: str, show: bool) -> None:
    """``show=True`` keeps the category in the feed despite the ratings; ``False`` removes the
    override so the automatic rule decides again. Raises ``ValueError`` for an unknown kind."""
    if kind not in KINDS:
        raise ValueError(f"unknown category kind: {kind!r}")
    pref = session.get(UserCategoryPref, (user.id, kind, key))
    if not show:
        if pref is not None:
            session.delete(pref)
    elif pref is None:
        session.add(UserCategoryPref(user_id=user.id, kind=kind, key=key, mode="show"))
    else:
        pref.mode = "show"
        pref.updated_at = datetime.now(UTC)
    session.flush()


def get_category_prefs(
    session: Session,
    store: MatrixStore,
    user: User,
    settings: RecommenderSettings | None = None,
    language: str = "en",
) -> list[CategoryView]:
    """Categories hidden by the rule right now and categories the user overrode, most disliked
    first. Names are in ``language`` (genres, anime) or as stored from TMDB."""
    settings = settings or RecommenderSettings()
    shown: set[CategoryKey] = {
        (kind, key)
        for kind, key in session.execute(
            select(UserCategoryPref.kind, UserCategoryPref.key).where(
                UserCategoryPref.user_id == user.id, UserCategoryPref.mode == "show"
            )
        )
    }
    data = store.get(user.pool)
    stats = {}
    hidden: set[CategoryKey] = set()
    if data.taste is not None:
        matrix, index = with_fresh_row(session, data, user)
        thresholds = settings.category_thresholds
        stats = category_stats(data.taste, matrix[index], thresholds.studio_max_movies)
        if settings.hide_categories:
            hidden = triggered_categories(stats, thresholds) - shown
    keys = hidden | shown
    names = _names(session, keys, language)
    views = []
    for key in keys:
        stat = stats.get(key)
        views.append(
            CategoryView(
                kind=key[0],
                key=key[1],
                name=names.get(key, key[1]),
                disliked=stat.disliked if stat else 0,
                rated=stat.rated if stat else 0,
                show=key in shown,
            )
        )
    return sorted(views, key=lambda v: (-v.disliked, v.kind, v.key))


CATEGORY_MOVIES_LIMIT = 50


@dataclass(frozen=True)
class CategoryMovie:
    """A movie the user rated that belongs to a category, with the user's rating."""

    movie: Movie
    value: int


def get_category_movies(
    session: Session,
    store: MatrixStore,
    user: User,
    kind: str,
    key: str,
    settings: RecommenderSettings | None = None,
    limit: int = CATEGORY_MOVIES_LIMIT,
) -> list[CategoryMovie] | None:
    """Movies of the category the user rated: dislikes first, then likes, each newest first.

    A movie belongs to the category by the same features as in ``category_stats`` (a studio only
    while recognisable); movies that are not matrix columns are ignored. ``None`` for an unknown
    category (unknown kind, or no such genre / collection / studio / anime key).
    """
    settings = settings or RecommenderSettings()
    if kind not in KINDS or not _names(session, {(kind, key)}, "en").get((kind, key)):
        return None
    taste = (data := store.get(user.pool)).taste
    if taste is None:
        return []
    wanted = (kind, key)
    studio_max = settings.category_thresholds.studio_max_movies
    rows = session.execute(
        select(Rating.movie_id, Rating.value)
        .where(Rating.user_id == user.id)
        .order_by(Rating.created_at.desc(), Rating.id.desc())
    ).all()
    found: list[tuple[int, int]] = []
    for movie_id, value in rows:
        col = bisect_left(data.movie_ids, movie_id)
        if (
            col < len(data.movie_ids)
            and data.movie_ids[col] == movie_id
            and wanted in column_categories(taste, col, studio_max)
        ):
            found.append((movie_id, value))
    found.sort(key=lambda item: item[1] > 0)  # stable: dislikes first, order kept
    found = found[:limit]
    movies = {
        m.id: m for m in session.scalars(select(Movie).where(Movie.id.in_([i for i, _ in found])))
    }
    return [CategoryMovie(movies[i], v) for i, v in found if i in movies]


def _names(session: Session, keys: set[CategoryKey], language: str) -> dict[CategoryKey, str]:
    names: dict[CategoryKey, str] = {}
    ids = {kind: [int(k) for kind_, k in keys if kind_ == kind and k.isdigit()] for kind in KINDS}
    if ids[GENRE_KIND]:
        for genre in session.scalars(select(Genre).where(Genre.id.in_(ids[GENRE_KIND]))):
            names[(GENRE_KIND, str(genre.id))] = (
                genre.name_ru if language == "ru" else genre.name_en
            )
    if ids[COLLECTION_KIND]:
        for coll in session.scalars(
            select(Collection).where(Collection.id.in_(ids[COLLECTION_KIND]))
        ):
            names[(COLLECTION_KIND, str(coll.id))] = coll.name
    if ids[STUDIO_KIND]:
        for company in session.scalars(select(Company).where(Company.id.in_(ids[STUDIO_KIND]))):
            names[(STUDIO_KIND, str(company.id))] = company.name
    names[(ANIME_KIND, ANIME_KEY)] = "Аниме" if language == "ru" else "Anime"
    return names
