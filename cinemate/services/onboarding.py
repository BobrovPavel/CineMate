"""Choosing well-known, controversial movies to show a new user during onboarding."""

from collections import Counter
from collections.abc import Collection, Sequence

import numpy as np
from scipy.sparse import csr_matrix
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, Rating, SeenMark, User

MAX_PER_GENRE = 3


def pick_onboarding_movies(
    matrix: csr_matrix,
    genres: Sequence[Sequence[str]],
    n: int = 20,
    pool: int = 300,
    exclude: Collection[int] = (),
) -> list[int]:
    """Return up to ``n`` movie (column) indices to show for taste discovery.

    Columns in ``exclude`` are dropped first. Of the rest, the ``pool`` movies with the
    most ratings are kept (ties: lower index first). The pool is ordered by rating
    variance, most controversial first (ties: lower index first); for +1/-1 ratings the
    variance is ``1 - mean**2``.

    Genre diversity: at most ``MAX_PER_GENRE`` movies sharing the same first genre are
    taken while other candidates remain; if fewer than ``n`` movies are found that way,
    the skipped ones fill the rest in the same order. Movies without genres are not
    limited. ``genres[i]`` lists the genres of column ``i``.
    """
    if n <= 0 or matrix.shape[1] == 0:
        return []
    col = matrix.tocsc()
    counts = np.diff(col.indptr)
    sums = np.asarray(col.sum(axis=0)).ravel().astype(float)
    excluded = set(exclude)
    candidates = [i for i in range(col.shape[1]) if counts[i] > 0 and i not in excluded]

    candidates.sort(key=lambda i: (-counts[i], i))
    candidates = candidates[: max(pool, 0)]
    variance = {i: 1.0 - (sums[i] / counts[i]) ** 2 for i in candidates}
    candidates.sort(key=lambda i: (-variance[i], i))

    picked: list[int] = []
    skipped: list[int] = []
    per_genre: Counter[str] = Counter()
    for i in candidates:
        if len(picked) >= n:
            break
        first = genres[i][0] if genres[i] else None
        if first is not None and per_genre[first] >= MAX_PER_GENRE:
            skipped.append(i)
            continue
        if first is not None:
            per_genre[first] += 1
        picked.append(i)
    for i in skipped:
        if len(picked) >= n:
            break
        picked.append(i)
    return picked


def onboarding_for_user(
    session: Session, store: MatrixStore, user: User, n: int = 20
) -> list[Movie]:
    """Pick onboarding movies for ``user``, skipping movies they already rated or marked."""
    ratings = store.get()
    done = set(session.scalars(select(Rating.movie_id).where(Rating.user_id == user.id)))
    done |= set(session.scalars(select(SeenMark.movie_id).where(SeenMark.user_id == user.id)))

    rows = session.scalars(select(Movie).where(Movie.id.in_(ratings.movie_ids))).all()
    by_id = {m.id: m for m in rows}
    genres = [by_id[mid].genres or [] if mid in by_id else [] for mid in ratings.movie_ids]
    exclude = {i for i, mid in enumerate(ratings.movie_ids) if mid in done}

    indices = pick_onboarding_movies(ratings.matrix, genres, n=n, exclude=exclude)
    return [by_id[ratings.movie_ids[i]] for i in indices if ratings.movie_ids[i] in by_id]
