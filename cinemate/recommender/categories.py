"""Categories a user disliked entirely, and similarity to disliked movies. No database.

A category is a franchise (TMDB collection), a recognisable studio, a genre or anime. It is
*triggered* for a user with no likes in it and at least ``min_dislikes`` dislikes; the movies of
a triggered category that stands within the first ``KEEP_TOP`` positions of the feed is moved
right after them, in its order, not removed; lower ones stay put (:func:`demote`).
"""

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix

from cinemate.recommender.taste import ANIMATION, ANIMATION_GENRE_ID, GENRE, FeatureKey, TasteData

COLLECTION_KIND, STUDIO_KIND, GENRE_KIND, ANIME_KIND = "collection", "studio", "genre", "anime"
KINDS = (COLLECTION_KIND, STUDIO_KIND, GENRE_KIND, ANIME_KIND)
ANIME_KEY = "anime"
KEEP_TOP = 20  # triggered categories stay out of this many first positions

CategoryKey = tuple[str, str]  # (kind, key as text)


@dataclass(frozen=True)
class CategoryThresholds:
    """When a category triggers: dislikes needed per kind and the size limit of a studio."""

    collection: int = 3
    studio: int = 3
    anime: int = 3
    genre: int = 5
    studio_max_movies: int = 150  # a studio with more rated movies in the pool is not recognisable

    def min_dislikes(self, kind: str) -> int:
        return {
            COLLECTION_KIND: self.collection,
            STUDIO_KIND: self.studio,
            ANIME_KIND: self.anime,
            GENRE_KIND: self.genre,
        }[kind]


@dataclass(frozen=True)
class CategoryStats:
    """Movies of a category the user rated: ``liked`` and ``disliked`` counts."""

    liked: int = 0
    disliked: int = 0

    @property
    def rated(self) -> int:
        return self.liked + self.disliked


def column_categories(
    data: TasteData, column: int, studio_max_movies: int
) -> tuple[CategoryKey, ...]:
    """Categories of a matrix column; a studio counts only when it is recognisable."""
    found: list[CategoryKey] = []
    collection = data.collection[column]
    if collection is not None:
        found.append((COLLECTION_KIND, str(collection)))
    if column < len(data.companies):
        for company in data.companies[column]:
            if data.company_sizes.get(company, 0) <= studio_max_movies:
                found.append((STUDIO_KIND, str(company)))
    for group in data.groups[column]:
        for kind, ident in group:
            if kind == GENRE:
                found.append((GENRE_KIND, str(ident)))
            elif kind == ANIMATION and ident == ANIME_KEY:
                found.append((ANIME_KIND, ANIME_KEY))
    return tuple(found)


def category_stats(
    data: TasteData, row: csr_matrix, studio_max_movies: int
) -> dict[CategoryKey, CategoryStats]:
    """Likes and dislikes of the user (matrix ``row``) per category of the movies they rated."""
    liked: Counter[CategoryKey] = Counter()
    disliked: Counter[CategoryKey] = Counter()
    for column, value in zip(row.indices.tolist(), row.data.tolist(), strict=True):
        if value == 0:
            continue
        target = liked if value > 0 else disliked
        for key in column_categories(data, column, studio_max_movies):
            target[key] += 1
    return {key: CategoryStats(liked[key], disliked[key]) for key in liked.keys() | disliked.keys()}


def triggered_categories(
    stats: dict[CategoryKey, CategoryStats], thresholds: CategoryThresholds
) -> set[CategoryKey]:
    """Categories with no likes and at least the threshold of dislikes."""
    return {
        key
        for key, stat in stats.items()
        if stat.liked == 0 and stat.disliked >= thresholds.min_dislikes(key[0])
    }


def demote[T](items: Sequence[T], is_hidden: Callable[[T], bool], keep: int = KEEP_TOP) -> list[T]:
    """Move hidden items out of the first ``keep`` positions; never move anything up.

    The top is the first ``keep`` non-hidden items. Hidden items that stood before the end of
    the top go right after it (position ``keep + 1``), in their order; everything after the top
    keeps its position, so a hidden item that stood lower stays where it was. With fewer
    non-hidden items than ``keep`` the hidden ones fill the rest. Nothing is dropped.
    """
    if keep <= 0:
        return [*(i for i in items if is_hidden(i)), *(i for i in items if not is_hidden(i))]
    top: list[T] = []
    moved: list[T] = []
    end = 0
    for position, item in enumerate(items):
        end = position + 1
        if is_hidden(item):
            moved.append(item)
        else:
            top.append(item)
            if len(top) == keep:
                break
    return top + moved + list(items[end:])


def dislike_similarity(
    matrix: csr_matrix, candidates: Sequence[int], disliked: Sequence[int]
) -> np.ndarray:
    """Per candidate column, the largest cosine similarity of its ratings column to any column
    in ``disliked``; ``0`` without dislikes or overlap.

    Only the candidate and disliked columns are used: no movie x movie matrix is built.
    """
    if not len(candidates) or not len(disliked):
        return np.zeros(len(candidates))
    cand = matrix[:, list(candidates)].astype(np.float32)
    dis = matrix[:, list(disliked)].astype(np.float32)
    dots = (cand.T @ dis).toarray()
    cand_norm = np.sqrt(np.asarray(abs(cand).sum(axis=0)).ravel())
    dis_norm = np.sqrt(np.asarray(abs(dis).sum(axis=0)).ravel())
    denom = np.outer(cand_norm, dis_norm)
    sims = np.divide(dots, denom, out=np.zeros_like(dots), where=denom > 0)
    return sims.max(axis=1).astype(np.float64)


def shown_taste_features(shown: Iterable[CategoryKey]) -> frozenset[FeatureKey]:
    """Taste-profile features of the categories the user chose to show: a genre and anime.

    Showing the animation genre also frees the "animation" feature that every cartoon carries.
    Collections and studios are not used by the taste profile.
    """
    features: set[FeatureKey] = set()
    for kind, key in shown:
        if kind == GENRE_KIND and key.isdigit():
            features.add((GENRE, int(key)))
            if int(key) == ANIMATION_GENRE_ID:
                features.add((ANIMATION, "animation"))
        elif kind == ANIME_KIND:
            features.add((ANIMATION, ANIME_KEY))
    return frozenset(features)


def disliked_columns(row: csr_matrix, exclude: Iterable[int] = ()) -> list[int]:
    """Columns the user disliked (``-1`` in ``row``)."""
    skip = set(exclude)
    return [j for j in row.indices[row.data < 0].tolist() if j not in skip]
