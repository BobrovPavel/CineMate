"""Recommender settings shared by the API, the service and ``cinemate evaluate``."""

import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from cinemate.recommender.categories import CategoryThresholds

# Named settings sets of the A/B test: ``taste`` keeps the configured settings.
AB_VARIANTS = ("control", "taste")


@dataclass(frozen=True)
class RecommenderSettings:
    """Parameters of the recommender: collaborative filtering and the switch to the fallback.

    Defaults were chosen from runs 2, 5, 6 and 8 (docs/EVALUATION.md): ``min_overlap=1``,
    K=150 (run 8, cold start from onboarding cards) and ``pop_penalty=0.75`` as a balance of
    precision and coverage, CF from 5 ratings and an exact top by likes in the fallback.
    """

    k: int = 150
    lam: float = 40.0
    min_overlap: int = 1
    pop_penalty: float = 0.75
    min_user_ratings: int = 5
    fallback_pool_factor: int = 1
    significance: int = 0
    blend_full_at: float = 0.0
    taste_weight: float = 0.5
    taste_interest_weight: float = 0.5
    dislike_item_weight: float = 0.5
    dislike_item_min_ratings: int = 50
    hide_studio_max_movies: int = 150
    hide_dislikes_collection: int = 3
    hide_dislikes_studio: int = 3
    hide_dislikes_anime: int = 3
    hide_dislikes_genre: int = 5
    hide_categories: bool = True
    ab_variants: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RecommenderSettings":
        """Read ``REC_K``, ``REC_LAMBDA``, ``REC_MIN_OVERLAP``, ``REC_POP_PENALTY``,
        ``REC_SIGNIFICANCE``, ``REC_BLEND_FULL_AT`` (0 turns the hybrid off),
        ``REC_MIN_USER_RATINGS``, ``REC_FALLBACK_POOL_FACTOR``, ``REC_TASTE_WEIGHT`` (``gamma``
        of the taste re-ranking, 0 turns it off), ``REC_TASTE_INTEREST_WEIGHT`` (``w_i``),
        ``REC_DISLIKE_ITEM_WEIGHT`` (``epsilon`` of the similarity-to-disliked penalty, 0 turns it
        off), ``REC_DISLIKE_ITEM_MIN_RATINGS``, ``REC_HIDE_STUDIO_MAX_MOVIES`` and
        ``REC_HIDE_DISLIKES_COLLECTION`` / ``_STUDIO`` / ``_ANIME`` / ``_GENRE`` (dislikes that
        hide a category) and ``REC_AB_VARIANTS`` (comma-separated variant names, see
        ``cinemate.services.ab``; empty turns the A/B test off).

        Empty or missing variables keep the defaults; invalid ones raise ``ValueError``
        naming the variable.
        """
        env = os.environ if environ is None else environ
        default = cls()
        return cls(
            k=_read(env, "REC_K", int, default.k, lambda v: v >= 1, ">= 1"),
            lam=_read(env, "REC_LAMBDA", float, default.lam, lambda v: v >= 0, ">= 0"),
            min_overlap=_read(
                env, "REC_MIN_OVERLAP", int, default.min_overlap, lambda v: v >= 1, ">= 1"
            ),
            pop_penalty=_read(
                env, "REC_POP_PENALTY", float, default.pop_penalty, lambda v: v >= 0, ">= 0"
            ),
            significance=_read(
                env, "REC_SIGNIFICANCE", int, default.significance, lambda v: v >= 0, ">= 0"
            ),
            blend_full_at=_read(
                env, "REC_BLEND_FULL_AT", float, default.blend_full_at, lambda v: v >= 0, ">= 0"
            ),
            taste_weight=_read(
                env, "REC_TASTE_WEIGHT", float, default.taste_weight, lambda v: v >= 0, ">= 0"
            ),
            taste_interest_weight=_read(
                env,
                "REC_TASTE_INTEREST_WEIGHT",
                float,
                default.taste_interest_weight,
                lambda v: v >= 0,
                ">= 0",
            ),
            dislike_item_weight=_read(
                env,
                "REC_DISLIKE_ITEM_WEIGHT",
                float,
                default.dislike_item_weight,
                lambda v: v >= 0,
                ">= 0",
            ),
            dislike_item_min_ratings=_read(
                env,
                "REC_DISLIKE_ITEM_MIN_RATINGS",
                int,
                default.dislike_item_min_ratings,
                lambda v: v >= 1,
                ">= 1",
            ),
            hide_studio_max_movies=_read(
                env,
                "REC_HIDE_STUDIO_MAX_MOVIES",
                int,
                default.hide_studio_max_movies,
                lambda v: v >= 1,
                ">= 1",
            ),
            hide_dislikes_collection=_read(
                env,
                "REC_HIDE_DISLIKES_COLLECTION",
                int,
                default.hide_dislikes_collection,
                lambda v: v >= 1,
                ">= 1",
            ),
            hide_dislikes_studio=_read(
                env,
                "REC_HIDE_DISLIKES_STUDIO",
                int,
                default.hide_dislikes_studio,
                lambda v: v >= 1,
                ">= 1",
            ),
            hide_dislikes_anime=_read(
                env,
                "REC_HIDE_DISLIKES_ANIME",
                int,
                default.hide_dislikes_anime,
                lambda v: v >= 1,
                ">= 1",
            ),
            hide_dislikes_genre=_read(
                env,
                "REC_HIDE_DISLIKES_GENRE",
                int,
                default.hide_dislikes_genre,
                lambda v: v >= 1,
                ">= 1",
            ),
            ab_variants=_read_variants(env),
            min_user_ratings=_read(
                env, "REC_MIN_USER_RATINGS", int, default.min_user_ratings, lambda v: v >= 1, ">= 1"
            ),
            fallback_pool_factor=_read(
                env,
                "REC_FALLBACK_POOL_FACTOR",
                int,
                default.fallback_pool_factor,
                lambda v: v >= 1,
                ">= 1",
            ),
        )

    @property
    def category_thresholds(self) -> CategoryThresholds:
        return CategoryThresholds(
            collection=self.hide_dislikes_collection,
            studio=self.hide_dislikes_studio,
            anime=self.hide_dislikes_anime,
            genre=self.hide_dislikes_genre,
            studio_max_movies=self.hide_studio_max_movies,
        )


def _read_variants(env: Mapping[str, str]) -> tuple[str, ...]:
    raw = env.get("REC_AB_VARIANTS", "").strip()
    if not raw:
        return ()
    names = tuple(part.strip() for part in raw.split(","))
    unknown = [n for n in names if n not in AB_VARIANTS]
    if unknown or len(set(names)) != len(names):
        raise ValueError(
            f"REC_AB_VARIANTS must be distinct names from {', '.join(AB_VARIANTS)}, got {raw!r}"
        )
    return names


def _read[T: (int, float)](
    env: Mapping[str, str],
    name: str,
    parse: Callable[[str], T],
    default: T,
    valid: Callable[[T], bool],
    requirement: str,
) -> T:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = parse(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if (isinstance(value, float) and math.isnan(value)) or not valid(value):
        raise ValueError(f"{name} must be {requirement}, got {raw!r}")
    return value
