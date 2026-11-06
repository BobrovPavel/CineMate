"""Collapse the parts of one franchise (TMDB collection) into a single feed card.

Pure logic over arbitrary hashable movie keys; the caller says what the collection of a key is,
which parts a collection has (ordered by release year, then id) and what the user has seen.
"""

from collections.abc import Callable, Collection, Hashable, Sequence
from dataclasses import dataclass
from typing import Literal

Mode = Literal["first", "next", "best"]


@dataclass(frozen=True)
class FranchiseInfo:
    """What the card says about its franchise.

    ``parts`` is the number of parts in the catalogue, ``unseen`` the parts the user has neither
    rated nor marked. ``mode``: ``first`` (new franchise, its first part), ``next`` (the part after
    the last liked one; ``rated_parts`` are the 1-based numbers of the parts the user has seen) or
    ``best`` (the best scored part).
    """

    collection_id: int
    parts: int
    unseen: int
    mode: Mode
    rated_parts: tuple[int, ...] = ()


def collapse_franchises[K: Hashable](
    candidates: Sequence[tuple[K, float]],
    collection: Callable[[K], int | None],
    parts_of: Callable[[int], Sequence[K]],
    seen: Collection[K],
    liked: Collection[K],
    selectable: Callable[[K], bool] = lambda _key: True,
) -> list[tuple[K, float, FranchiseInfo | None]]:
    """Keep one part per collection, in the place of its best scored part.

    ``candidates`` are ``(key, score)`` already ordered; none of them is in ``seen``. The
    representative takes the position and score of the collection's best candidate. Which part it
    is: if the user liked some part, the first unseen selectable part after the last liked one;
    if they saw nothing, the first part when it is selectable; otherwise the best candidate itself.
    Movies without a collection pass unchanged. A collection without candidates does not appear.
    """
    first_position: dict[int, int] = {}
    for position, (key, _) in enumerate(candidates):
        coll = collection(key)
        if coll is not None:
            first_position.setdefault(coll, position)

    result: list[tuple[K, float, FranchiseInfo | None]] = []
    for position, (key, score) in enumerate(candidates):
        coll = collection(key)
        if coll is None:
            result.append((key, score, None))
            continue
        if first_position[coll] != position:
            continue
        parts = list(parts_of(coll))
        seen_numbers = tuple(i + 1 for i, p in enumerate(parts) if p in seen)
        liked_indexes = [i for i, p in enumerate(parts) if p in liked]

        def usable(part: K) -> bool:
            return part not in seen and selectable(part)

        chosen, mode = key, "best"
        if liked_indexes:
            after = next((p for p in parts[max(liked_indexes) + 1 :] if usable(p)), None)
            if after is not None:
                chosen, mode = after, "next"
        elif not seen_numbers and parts and usable(parts[0]):
            chosen, mode = parts[0], "first"
        info = FranchiseInfo(
            collection_id=coll,
            parts=max(len(parts), 1),
            unseen=sum(1 for p in parts if p not in seen) if parts else 1,
            mode=mode,  # type: ignore[arg-type]
            rated_parts=seen_numbers if mode == "next" else (),
        )
        result.append((chosen, score, info))
    return result
