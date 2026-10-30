"""Taste profile: what a user likes by content (genre, type, animation, decade, language).

Pure functions, no database. A movie has features grouped by kind; a user's profile gives each
feature ``f`` a contribution ``q_f + interest_weight * i_f`` where, with ``L_f`` / ``D_f`` the
user's likes / dislikes of movies having ``f`` and ``E_f`` the likes expected from the pool::

    q_f = (L_f - D_f) / (L_f + D_f + prior)        quality: likes against dislikes
    i_f = ln((L_f + 1) / (E_f + 1))                interest: more often liked than on average
    E_f = (user's likes) * base_f                  base_f: share of f among all pool likes

A movie's taste score is the mean over its feature groups of the mean contribution inside the
group; a movie without features scores 0. :func:`rerank` blends it with the CF score and
:func:`diversify` limits genre and franchise runs.
"""

import math
from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix

FeatureKey = tuple[str, int | str]
Groups = tuple[tuple[FeatureKey, ...], ...]

GENRE, TYPE, ANIMATION, DECADE, LANGUAGE = "genre", "type", "animation", "decade", "language"
ANIMATION_GENRE_ID = 16
JAPANESE = "ja"

DEFAULT_PRIOR = 2.0
DEFAULT_INTEREST_WEIGHT = 0.5
NOT_INTERESTED_WEIGHT = 0.5  # a "not interested" mark counts as half a dislike
MIN_REASON_LIKES = 3
MIN_REASON_CONTRIBUTION = 0.5
CANDIDATES = 200
WINDOW = 10
MAX_SAME_GENRE = 4
MAX_SAME_COLLECTION = 2


@dataclass(frozen=True)
class MovieFeatures:
    """Content features of one movie; every field may be unknown."""

    genres: tuple[int, ...] = ()
    kind: str | None = None  # "movie" or "tv"
    language: str | None = None  # ISO 639-1 original language
    year: int | None = None
    collection_id: int | None = None
    companies: tuple[int, ...] = ()  # production company (studio) ids


def movie_groups(features: MovieFeatures) -> Groups:
    """The non-empty feature groups of a movie: genres, type, animation/anime, decade, language."""
    groups: list[tuple[FeatureKey, ...]] = []
    if features.genres:
        groups.append(tuple((GENRE, g) for g in features.genres))
    if features.kind:
        groups.append(((TYPE, features.kind),))
    if ANIMATION_GENRE_ID in features.genres:
        animation: list[FeatureKey] = [(ANIMATION, "animation")]
        if features.language == JAPANESE:
            animation.append((ANIMATION, "anime"))
        groups.append(tuple(animation))
    if features.year is not None:
        groups.append(((DECADE, features.year // 10 * 10),))
    if features.language:
        groups.append(((LANGUAGE, features.language),))
    return tuple(groups)


@dataclass(frozen=True)
class TasteData:
    """Features of the matrix columns plus the pool-wide shares ``base_f`` of the likes."""

    groups: list[Groups]
    base: dict[FeatureKey, float]
    primary_genre: list[int | None]
    collection: list[int | None]
    companies: list[tuple[int, ...]] = field(default_factory=list)
    company_sizes: dict[int, int] = field(default_factory=dict)  # company id -> columns it has


def build_taste_data(features: Sequence[MovieFeatures], likes: np.ndarray) -> TasteData:
    """Taste data for columns with ``features``; ``likes[j]`` is the like count of column ``j``.

    ``base_f`` is the share of the pool's likes that fall on movies having feature ``f``. The
    primary genre of a movie is its rarest genre by that share (ties: lower id), the most
    telling one for diversity.
    """
    groups = [movie_groups(f) for f in features]
    total = float(likes.sum())
    counts: Counter[FeatureKey] = Counter()
    for column_groups, n in zip(groups, likes.tolist(), strict=True):
        if n:
            for group in column_groups:
                for key in group:
                    counts[key] += n
    base = {key: n / total for key, n in counts.items()} if total else {}
    primary: list[int | None] = []
    for f in features:
        if f.genres:
            primary.append(min(f.genres, key=lambda g: (base.get((GENRE, g), 0.0), g)))
        else:
            primary.append(None)
    company_sizes: Counter[int] = Counter(c for f in features for c in set(f.companies))
    return TasteData(
        groups=groups,
        base=base,
        primary_genre=primary,
        collection=[f.collection_id for f in features],
        companies=[tuple(f.companies) for f in features],
        company_sizes=dict(company_sizes),
    )


@dataclass(frozen=True)
class TasteProfile:
    """A user's counts per feature and the parameters of the contribution formula."""

    likes: dict[FeatureKey, float]
    dislikes: dict[FeatureKey, float]
    n_likes: int
    base: dict[FeatureKey, float] = field(repr=False)
    prior: float = DEFAULT_PRIOR
    interest_weight: float = DEFAULT_INTEREST_WEIGHT

    def contribution(self, key: FeatureKey) -> float:
        """``q_f + interest_weight * i_f``; a feature the user never met has ``q = 0``."""
        liked = self.likes.get(key, 0.0)
        disliked = self.dislikes.get(key, 0.0)
        quality = (liked - disliked) / (liked + disliked + self.prior)
        expected = self.n_likes * self.base.get(key, 0.0)
        interest = math.log((liked + 1) / (expected + 1))
        return quality + self.interest_weight * interest


def build_profile(
    data: TasteData,
    liked: Iterable[int],
    disliked: Iterable[int] = (),
    not_interested: Iterable[int] = (),
    prior: float = DEFAULT_PRIOR,
    interest_weight: float = DEFAULT_INTEREST_WEIGHT,
) -> TasteProfile:
    """Profile from column indices; ``not_interested`` columns count as dislikes of weight 0.5."""
    likes: Counter[FeatureKey] = Counter()
    dislikes: Counter[FeatureKey] = Counter()
    n_likes = 0
    for columns, weight, target in (
        (liked, 1.0, likes),
        (disliked, 1.0, dislikes),
        (not_interested, NOT_INTERESTED_WEIGHT, dislikes),
    ):
        for j in columns:
            if target is likes:
                n_likes += 1
            for group in data.groups[j]:
                for key in group:
                    target[key] += weight
    return TasteProfile(
        likes=dict(likes),
        dislikes=dict(dislikes),
        n_likes=n_likes,
        base=data.base,
        prior=prior,
        interest_weight=interest_weight,
    )


def taste_score(profile: TasteProfile, groups: Groups) -> float:
    """Mean over the groups of the mean contribution inside the group; 0 without features."""
    if not groups:
        return 0.0
    return sum(
        sum(profile.contribution(key) for key in group) / len(group) for group in groups
    ) / len(groups)


def zscore(values: Sequence[float]) -> np.ndarray:
    """Standardize ``values``; a constant list becomes zeros."""
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return array
    std = array.std()
    return (array - array.mean()) / std if std > 0 else np.zeros_like(array)


def rerank(
    cf_scores: Sequence[float],
    taste_scores: Sequence[float],
    weight: float,
    penalties: Sequence[float] | None = None,
    penalty_weight: float = 0.0,
) -> list[int]:
    """Positions ordered by ``z(cf) + weight * z(taste) - penalty_weight * z(penalty)``
    descending (ties keep the CF order)."""
    combined = zscore(cf_scores) + weight * zscore(taste_scores)
    if penalties is not None and penalty_weight > 0:
        combined = combined - penalty_weight * zscore(penalties)
    return sorted(range(len(combined)), key=lambda i: (-combined[i], i))


def diversify(
    order: Sequence[int],
    primary_genre: Callable[[int], Hashable | None],
    collection: Callable[[int], Hashable | None],
    window: int = WINDOW,
    max_genre: int = MAX_SAME_GENRE,
    max_collection: int = MAX_SAME_COLLECTION,
) -> list[int]:
    """Reorder so that any ``window`` consecutive items hold at most ``max_genre`` with the same
    primary genre and ``max_collection`` of one collection.

    Greedy: each position takes the first remaining item that keeps the limits for the window
    ending there; an item that does not fit moves lower, the order of the rest is kept. When
    nothing fits, the first remaining item is taken, so nothing is dropped.
    """
    remaining = list(order)
    result: list[int] = []
    while remaining:
        tail = result[-(window - 1) :] if window > 1 else []
        genres = Counter(g for i in tail if (g := primary_genre(i)) is not None)
        collections = Counter(c for i in tail if (c := collection(i)) is not None)
        pick = 0
        for position, item in enumerate(remaining):
            genre, coll = primary_genre(item), collection(item)
            if genre is not None and genres[genre] >= max_genre:
                continue
            if coll is not None and collections[coll] >= max_collection:
                continue
            pick = position
            break
        result.append(remaining.pop(pick))
    return result


def taste_reason(
    profile: TasteProfile,
    groups: Groups,
    kinds: Iterable[str] = (GENRE, TYPE, ANIMATION, DECADE, LANGUAGE),
) -> FeatureKey | None:
    """The feature of the movie with the largest positive contribution, if the profile is sure.

    Sure means at least ``MIN_REASON_LIKES`` likes of the feature and a contribution above
    ``MIN_REASON_CONTRIBUTION``; otherwise ``None``. Only ``kinds`` are considered.
    """
    allowed = set(kinds)
    best: FeatureKey | None = None
    best_value = MIN_REASON_CONTRIBUTION
    for group in groups:
        for key in group:
            if key[0] not in allowed or profile.likes.get(key, 0.0) < MIN_REASON_LIKES:
                continue
            value = profile.contribution(key)
            if value > best_value:
                best, best_value = key, value
    return best


def rerank_candidates(
    data: TasteData,
    row: csr_matrix,
    candidates: Sequence[tuple[int, float]],
    weight: float,
    interest_weight: float = DEFAULT_INTEREST_WEIGHT,
    not_interested: Iterable[int] = (),
    penalties: Sequence[float] | None = None,
    penalty_weight: float = 0.0,
) -> tuple[list[tuple[int, float]], TasteProfile]:
    """Re-rank CF ``(column, score)`` candidates for the user whose matrix row is ``row``.

    The profile is built from the row's likes and dislikes (``+1`` / ``-1``) and the
    ``not_interested`` columns; the order is :func:`rerank` followed by :func:`diversify`.
    ``penalties[i]`` (e.g. the similarity to disliked movies) of candidate ``i`` is subtracted
    as ``penalty_weight * z(penalty)``. Returns the new order (scores unchanged) and the profile.
    """
    profile = build_profile(
        data,
        liked=row.indices[row.data > 0].tolist(),
        disliked=row.indices[row.data < 0].tolist(),
        not_interested=not_interested,
        interest_weight=interest_weight,
    )
    tastes = [taste_score(profile, data.groups[j]) for j, _ in candidates]
    order = rerank([score for _, score in candidates], tastes, weight, penalties, penalty_weight)
    order = diversify(
        order,
        lambda i: data.primary_genre[candidates[i][0]],
        lambda i: data.collection[candidates[i][0]],
    )
    return [candidates[i] for i in order], profile
