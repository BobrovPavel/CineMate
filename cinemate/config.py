"""Recommender settings shared by the API, the service and ``cinemate evaluate``."""

import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RecommenderSettings:
    """Parameters of the recommender: collaborative filtering and the switch to the fallback.

    Defaults were chosen from runs 2, 5 and 6 (docs/EVALUATION.md): ``min_overlap=1``,
    K=60 and ``pop_penalty=0.75`` as a balance of precision and coverage, CF from 5 ratings
    and an exact top by likes in the fallback.
    """

    k: int = 60
    lam: float = 40.0
    min_overlap: int = 1
    pop_penalty: float = 0.75
    min_user_ratings: int = 5
    fallback_pool_factor: int = 1

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RecommenderSettings":
        """Read ``REC_K``, ``REC_LAMBDA``, ``REC_MIN_OVERLAP``, ``REC_POP_PENALTY``,
        ``REC_MIN_USER_RATINGS`` and ``REC_FALLBACK_POOL_FACTOR``.

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


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def resolve_cookie_secure(flag: bool, environ: Mapping[str, str] | None = None) -> bool:
    """Decide the ``Secure`` flag of the session cookie: the flag, then ``COOKIE_SECURE``, then off.

    ``1/true/yes/on`` enable and ``0/false/no/off`` disable (case-insensitive); an empty or
    missing variable means off. Any other value raises ``ValueError`` naming the variable.
    """
    if flag:
        return True
    env = os.environ if environ is None else environ
    raw = env.get("COOKIE_SECURE", "").strip().lower()
    if not raw or raw in _FALSE_VALUES:
        return False
    if raw in _TRUE_VALUES:
        return True
    raise ValueError(f"COOKIE_SECURE must be one of 1/true/yes/on or 0/false/no/off, got {raw!r}")
