"""Recommender settings shared by the API, the service and ``cinemate evaluate``."""

import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RecommenderSettings:
    """Parameters of the collaborative recommender.

    Defaults follow the second ``tune`` run (docs/EVALUATION.md): precision@10 = 0.1997.
    """

    k: int = 40
    lam: float = 40.0
    min_overlap: int = 3
    pop_penalty: float = 1.0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RecommenderSettings":
        """Read ``REC_K``, ``REC_LAMBDA``, ``REC_MIN_OVERLAP`` and ``REC_POP_PENALTY``.

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
