"""Movie features for the offline evaluation of the taste re-ranking."""

from pathlib import Path

from cinemate.genres import legacy_genre_ids
from cinemate.movielens import parse_movies
from cinemate.recommender.taste import MovieFeatures


def movielens_features(movies_csv: Path | str) -> dict[int | str, MovieFeatures]:
    """Genres (translated to TMDB ids) and release year of every movie in ``movies.csv``.

    MovieLens has no type, language or franchise, so those features stay unknown.
    """
    return {
        movie.movielens_id: MovieFeatures(
            genres=tuple(sorted(legacy_genre_ids(movie.genres)[0])), year=movie.year
        )
        for movie in parse_movies(movies_csv)
    }
