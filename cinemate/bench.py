"""Benchmark of the matrix load and ``get_recommendations`` (``bench-recommendations``)."""

import random
import statistics
import time
from dataclasses import dataclass

import numpy as np
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.orm import sessionmaker

from cinemate.db.features import seed_genres
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, MovieGenre, Rating, User
from cinemate.genres import GENRES
from cinemate.services.recommendations import get_recommendations

_INSERT_CHUNK = 50_000
_RATINGS_PER_USER = 150
_MAX_MOVIES = 20_000


@dataclass(frozen=True)
class BenchResult:
    load_seconds: float
    users: int
    movies: int
    nonzero: int
    matrix_mb: float
    requests: int
    p50_ms: float
    p95_ms: float


def fill_synthetic(engine: Engine, ratings: int, pool: str, seed: int = 0) -> int:
    """Insert about ``ratings`` random ratings (skewed movie popularity) into an empty database.

    Returns the number of ratings inserted (duplicate user/movie pairs are dropped). Raises
    ``ValueError`` if the database already has users, so real data is never mixed with noise.
    """
    if ratings < 1:
        raise ValueError("--synthetic must be >= 1")
    seed_genres(engine)
    with engine.begin() as conn:
        if conn.scalar(select(func.count()).select_from(User)):
            raise ValueError("--synthetic needs an empty database")
        n_users = max(2, ratings // _RATINGS_PER_USER)
        n_movies = min(_MAX_MOVIES, max(10, ratings // 2))
        conn.execute(insert(User), [{"pool": pool, "is_synthetic": True}] * n_users)
        feature_rng = np.random.default_rng(seed + 1)
        years = feature_rng.integers(1950, 2025, n_movies)
        languages = feature_rng.choice(["en", "en", "en", "fr", "ja", "ru"], n_movies)
        conn.execute(
            insert(Movie),
            [
                {
                    "title": f"Movie {i}",
                    "tmdb_type": "movie" if i % 5 else "tv",
                    "year": int(years[i]),
                    "original_language": str(languages[i]),
                }
                for i in range(n_movies)
            ],
        )
        user_ids = np.array(list(conn.scalars(select(User.id).order_by(User.id))))
        movie_ids = np.array(list(conn.scalars(select(Movie.id).order_by(Movie.id))))

        genre_ids = [g.id for g in GENRES]
        genre_rows = [
            {"movie_id": int(movie_id), "genre_id": int(genre)}
            for movie_id in movie_ids
            for genre in feature_rng.choice(
                genre_ids, size=int(feature_rng.integers(1, 4)), replace=False
            )
        ]
        for start in range(0, len(genre_rows), _INSERT_CHUNK):
            conn.execute(insert(MovieGenre), genre_rows[start : start + _INSERT_CHUNK])

        rng = np.random.default_rng(seed)
        weights = 1.0 / (np.arange(n_movies) + 50.0)
        draw = int(ratings * 1.15) + 10
        pairs = rng.integers(0, n_users, draw) * n_movies + rng.choice(
            n_movies, draw, p=weights / weights.sum()
        )
        pairs = np.unique(pairs)
        rng.shuffle(pairs)
        pairs = pairs[:ratings]
        us, ms = pairs // n_movies, pairs % n_movies
        values = np.where(rng.random(len(pairs)) < 0.7, 1, -1)
        for start in range(0, len(pairs), _INSERT_CHUNK):
            sl = slice(start, start + _INSERT_CHUNK)
            conn.execute(
                insert(Rating),
                [
                    {"user_id": int(u), "movie_id": int(m), "value": int(v)}
                    for u, m, v in zip(user_ids[us[sl]], movie_ids[ms[sl]], values[sl], strict=True)
                ],
            )
    return len(pairs)


def run_bench(engine: Engine, pool: str, requests: int, seed: int) -> BenchResult:
    """Time the matrix load, then ``requests`` calls of ``get_recommendations`` for random users."""
    factory = sessionmaker(engine, expire_on_commit=False)
    store = MatrixStore(factory)
    started = time.perf_counter()
    data = store.get(pool)
    load_seconds = time.perf_counter() - started

    matrix = data.matrix
    matrix_mb = (matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes) / 1e6
    if not data.user_ids:
        raise ValueError(f"pool {pool!r} has no ratings")

    rng = random.Random(seed)
    timings: list[float] = []
    for _ in range(requests):
        user_id = rng.choice(data.user_ids)
        with factory() as session:
            user = session.get(User, user_id)
            started = time.perf_counter()
            get_recommendations(session, store, user, rng=random.Random(seed))
            timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    p95 = timings[min(len(timings) - 1, int(0.95 * len(timings)))] if timings else 0.0
    return BenchResult(
        load_seconds=load_seconds,
        users=matrix.shape[0],
        movies=matrix.shape[1],
        nonzero=int(matrix.nnz),
        matrix_mb=matrix_mb,
        requests=len(timings),
        p50_ms=statistics.median(timings) if timings else 0.0,
        p95_ms=p95,
    )


def format_bench(result: BenchResult) -> str:
    return "\n".join(
        [
            f"matrix load: {result.load_seconds:.2f} s",
            f"matrix size: {result.users} users x {result.movies} movies, "
            f"{result.nonzero} non-zero",
            f"matrix arrays: {result.matrix_mb:.1f} MB",
            f"get_recommendations over {result.requests} requests: "
            f"p50 {result.p50_ms:.0f} ms, p95 {result.p95_ms:.0f} ms",
        ]
    )
