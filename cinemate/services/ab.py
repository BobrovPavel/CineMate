"""A/B test of recommender variants: deterministic assignment and per-variant settings.

A variant is a named set of recommender settings (``cinemate.config.AB_VARIANTS``):

* ``control`` - no taste re-ranking, no similarity-to-disliked penalty, no hidden categories;
* ``taste`` - the settings as configured.

The variant is computed from the user id, never stored: changing ``REC_AB_VARIANTS``
reassigns everyone.
"""

import hashlib
from dataclasses import replace

from cinemate.config import RecommenderSettings


def assign_variant(settings: RecommenderSettings, user_id: int) -> str | None:
    """The user's variant: a stable hash of ``user_id`` modulo the number of variants.

    ``None`` when the A/B test is off (``settings.ab_variants`` is empty).
    """
    variants = settings.ab_variants
    if not variants:
        return None
    digest = hashlib.sha256(str(user_id).encode()).digest()
    return variants[int.from_bytes(digest[:8], "big") % len(variants)]


def settings_for_variant(settings: RecommenderSettings, variant: str | None) -> RecommenderSettings:
    """Settings the ``variant`` recommends with; ``None`` and ``taste`` keep ``settings``."""
    if variant == "control":
        return replace(settings, taste_weight=0.0, dislike_item_weight=0.0, hide_categories=False)
    return settings
