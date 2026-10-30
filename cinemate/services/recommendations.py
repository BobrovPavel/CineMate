"""Recommendations for a database user: movies, scores and honest explanations.

No web framework is used here. The session is only read from.
"""

import random
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy.sparse import csr_matrix, vstack
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.config import RecommenderSettings
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Genre, Movie, Rating, SeenMark, User, UserCategoryPref
from cinemate.recommender.categories import (
    category_stats,
    column_categories,
    demote,
    dislike_similarity,
    disliked_columns,
    triggered_categories,
)
from cinemate.recommender.explain import explain
from cinemate.recommender.matrix import RatingsMatrix
from cinemate.recommender.similarity import find_neighbors
from cinemate.recommender.strategy import recommend_with_strategy
from cinemate.recommender.taste import (
    ANIMATION,
    CANDIDATES,
    DECADE,
    GENRE,
    LANGUAGE,
    TYPE,
    FeatureKey,
    rerank_candidates,
    taste_reason,
)

# Taste features worth telling the user about: type, decade and language would be
# the same line under almost every movie.
REASON_KINDS = (GENRE, ANIMATION)

# Marks that remove a movie from the results; ``not_seen`` is only a signal (VISION.md).
EXCLUDING_MARKS = ("watched", "not_interested")


@dataclass(frozen=True)
class TasteReason:
    """The taste feature behind a recommendation: ``kind`` (genre, type, animation, decade,
    language), its ``id`` as text and a ``name`` in the request language."""

    kind: str
    id: str
    name: str


@dataclass(frozen=True)
class RecommendedMovie:
    """A recommended movie with its score and explanation.

    For the fallback strategy ``liked_by`` is 0, ``because_of`` is empty and there is no
    ``because_taste``. ``score`` is the CF score; the order may differ because of the taste.
    """

    movie: Movie
    score: float
    liked_by: int = 0
    because_of: list[Movie] = field(default_factory=list)
    because_taste: TasteReason | None = None


@dataclass(frozen=True)
class RecommendationsResult:
    strategy: Literal["collaborative", "fallback"]
    items: list[RecommendedMovie]


_TYPE_NAMES = {"movie": ("фильмы", "movies"), "tv": ("сериалы", "TV shows")}
_ANIMATION_NAMES = {"animation": ("мультфильмы", "animation"), "anime": ("аниме", "anime")}
# language code -> (Russian prepositional form, English name)
_LANGUAGE_NAMES = {
    "en": ("английском", "English"),
    "ru": ("русском", "Russian"),
    "ja": ("японском", "Japanese"),
    "ko": ("корейском", "Korean"),
    "fr": ("французском", "French"),
    "de": ("немецком", "German"),
    "es": ("испанском", "Spanish"),
    "it": ("итальянском", "Italian"),
    "zh": ("китайском", "Chinese"),
    "hi": ("хинди", "Hindi"),
}


def _reason_name(key: FeatureKey, genre_names: dict[int, str], language: str) -> str | None:
    """Display name of a taste feature in ``language`` (``ru`` or English); ``None`` if unknown."""
    kind, ident = key
    ru = language == "ru"
    if kind == GENRE:
        return genre_names.get(int(ident))
    if kind == TYPE:
        names = _TYPE_NAMES.get(str(ident))
    elif kind == ANIMATION:
        names = _ANIMATION_NAMES.get(str(ident))
    elif kind == DECADE:
        return f"фильмы {ident}-х" if ru else f"movies of the {ident}s"
    elif kind == LANGUAGE:
        found = _LANGUAGE_NAMES.get(str(ident))
        if found is None:
            return None
        return f"фильмы на {found[0]}" if ru else f"movies in {found[1]}"
    else:
        return None
    return names[0 if ru else 1] if names else None


def with_fresh_row(session: Session, data: RatingsMatrix, user: User) -> tuple[csr_matrix, int]:
    """Return the cached matrix with ``user``'s row taken from the database, and its index.

    The cached matrix may be older than the user's latest ratings. The row is replaced (or
    appended for a user absent from the matrix); ratings of movies that are not matrix columns
    are ignored. The cached matrix itself is never modified. When the row differs from the cache
    (the user rated since the last rebuild, or is new) the matrix is copied, which is O(nnz).
    """
    matrix = data.matrix
    cols: list[int] = []
    values: list[int] = []
    for movie_id, value in session.execute(
        select(Rating.movie_id, Rating.value).where(Rating.user_id == user.id)
    ):
        col = bisect_left(data.movie_ids, movie_id)
        if col < len(data.movie_ids) and data.movie_ids[col] == movie_id:
            cols.append(col)
            values.append(value)
    fresh = csr_matrix(
        (
            np.array(values, dtype=matrix.dtype),
            (np.zeros(len(cols), dtype=int), np.array(cols, dtype=int)),
        ),
        shape=(1, matrix.shape[1]),
    )

    row = bisect_left(data.user_ids, user.id)
    if row < len(data.user_ids) and data.user_ids[row] == user.id:
        if (matrix[row] != fresh).nnz == 0:
            return matrix, row
        parts = [matrix[:row], fresh, matrix[row + 1 :]]
        return vstack(parts).tocsr(), row
    return vstack([matrix, fresh]).tocsr(), matrix.shape[0]


def get_recommendations(
    session: Session,
    store: MatrixStore,
    user: User,
    limit: int = 20,
    rng: random.Random | None = None,
    settings: RecommenderSettings | None = None,
    language: str = "en",
) -> RecommendationsResult:
    """Recommend up to ``limit`` movies to ``user`` using the matrix cached in ``store``.

    The user's own row is read from the database, so their latest ratings count immediately;
    other users' ratings arrive with the store's next background rebuild.

    ``settings`` defaults to :class:`RecommenderSettings` defaults.

    A user absent from the matrix gets the fallback. Movies marked ``watched`` or
    ``not_interested`` are excluded; ``not_seen`` does not exclude. Collaborative items carry
    ``liked_by`` and up to 3 ``because_of`` movies; fallback items carry neither.

    With ``settings.taste_weight`` > 0 the collaborative strategy takes up to ``CANDIDATES``
    candidates, re-ranks them by ``z(cf) + weight * z(taste)`` (the taste profile comes from the
    user's ratings and ``not_interested`` marks over the features cached in the store), limits
    genre and franchise runs and cuts the list to ``limit``. ``because_taste`` names the
    feature behind the movie when the profile is sure about it, in ``language``.
    """
    settings = settings or RecommenderSettings()
    if limit <= 0:
        return RecommendationsResult(strategy="fallback", items=[])

    data = store.get(user.pool)
    matrix, user_index = with_fresh_row(session, data, user)

    marks = session.execute(
        select(SeenMark.movie_id, SeenMark.type).where(
            SeenMark.user_id == user.id, SeenMark.type.in_(EXCLUDING_MARKS)
        )
    ).all()
    excluded_ids = {movie_id for movie_id, _ in marks}
    not_interested_ids = {movie_id for movie_id, mark in marks if mark == "not_interested"}
    excluded_cols = {i for i, movie_id in enumerate(data.movie_ids) if movie_id in excluded_ids}

    neighbors = None
    if settings.blend_full_at <= 0 and int((matrix[user_index].data != 0).sum()) >= (
        settings.min_user_ratings
    ):
        # shared by the scoring and the explanations: the search is the costly step
        neighbors = find_neighbors(
            matrix,
            user_index,
            k=settings.k,
            min_overlap=settings.min_overlap,
            significance=settings.significance,
        )

    taste = data.taste
    row = matrix[user_index]
    hidden: set[tuple[str, str]] = set()
    if taste is not None and settings.hide_categories:
        shown = {
            (kind, key)
            for kind, key in session.execute(
                select(UserCategoryPref.kind, UserCategoryPref.key).where(
                    UserCategoryPref.user_id == user.id, UserCategoryPref.mode == "show"
                )
            )
        }
        thresholds = settings.category_thresholds
        stats = category_stats(taste, row, thresholds.studio_max_movies)
        hidden = triggered_categories(stats, thresholds) - shown
    disliked_cols = disliked_columns(row)
    penalty_on = (
        settings.dislike_item_weight > 0
        and bool(disliked_cols)
        and row.nnz >= settings.dislike_item_min_ratings
    )
    rerank_on = taste is not None and (settings.taste_weight > 0 or penalty_on)
    # Over-fetch so that filtering excluded movies still leaves ``limit`` items.
    wanted = max(limit, CANDIDATES) if rerank_on or hidden else limit
    rec = recommend_with_strategy(
        matrix,
        user_index,
        n=wanted + len(excluded_cols),
        k=settings.k,
        min_overlap=settings.min_overlap,
        lam=settings.lam,
        pop_penalty=settings.pop_penalty,
        significance=settings.significance,
        min_user_ratings=settings.min_user_ratings,
        fallback_pool_factor=settings.fallback_pool_factor,
        blend_full_at=settings.blend_full_at,
        rng=rng,
        neighbors=neighbors,
    )
    candidates = [(j, s) for j, s in rec.items if j not in excluded_cols][:wanted]

    profile = None
    if rerank_on and taste is not None and rec.strategy == "collaborative" and candidates:
        rated = set(row.indices.tolist())
        candidates, profile = rerank_candidates(
            taste,
            row,
            candidates,
            settings.taste_weight,
            settings.taste_interest_weight,
            not_interested=[
                j
                for movie_id in not_interested_ids
                if (j := bisect_left(data.movie_ids, movie_id)) < len(data.movie_ids)
                and data.movie_ids[j] == movie_id
                and j not in rated
            ],
            penalties=dislike_similarity(matrix, [j for j, _ in candidates], disliked_cols)
            if penalty_on
            else None,
            penalty_weight=settings.dislike_item_weight,
        )
    if hidden and taste is not None:
        studio_max = settings.hide_studio_max_movies
        candidates = demote(
            candidates,
            lambda c: any(key in hidden for key in column_categories(taste, c[0], studio_max)),
        )
    picked = candidates[:limit]

    if rec.strategy != "collaborative":
        neighbors = []
    elif neighbors is None:
        neighbors = find_neighbors(
            matrix,
            user_index,
            k=settings.k,
            min_overlap=settings.min_overlap,
            significance=settings.significance,
        )
    explanations = {j: explain(matrix, user_index, j, neighbors) for j, _ in picked}

    needed = {data.movie_ids[j] for j, _ in picked}
    for exp in explanations.values():
        needed.update(data.movie_ids[b] for b in exp.because_of)
    movies = {m.id: m for m in session.scalars(select(Movie).where(Movie.id.in_(needed)))}

    reasons: dict[int, TasteReason] = {}
    if profile is not None and taste is not None and settings.taste_weight > 0:
        genre_names = {
            g.id: (g.name_ru if language == "ru" else g.name_en)
            for g in session.scalars(select(Genre))
        }
        for j, _ in picked:
            key = taste_reason(profile, taste.groups[j], kinds=REASON_KINDS)
            name = _reason_name(key, genre_names, language) if key else None
            if key and name:
                reasons[j] = TasteReason(kind=key[0], id=str(key[1]), name=name)

    items = [
        RecommendedMovie(
            movie=movies[data.movie_ids[j]],
            score=score,
            liked_by=explanations[j].liked_by if neighbors else 0,
            because_of=[movies[data.movie_ids[b]] for b in explanations[j].because_of]
            if neighbors
            else [],
            because_taste=reasons.get(j),
        )
        for j, score in picked
    ]
    return RecommendationsResult(strategy=rec.strategy, items=items)
