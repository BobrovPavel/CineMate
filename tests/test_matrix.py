from scipy.sparse import csr_matrix

from cinemate.binarize import MovieLensBinarizer
from cinemate.movielens import Rating
from cinemate.recommender.matrix import build_matrix


def _build(*ratings: tuple[int, int, float]):
    return build_matrix([Rating(*r) for r in ratings], MovieLensBinarizer())


def test_values_are_plus_and_minus_one():
    result = _build((1, 10, 5.0), (1, 20, 1.0), (2, 10, 4.0))

    assert isinstance(result.matrix, csr_matrix)
    assert result.matrix.shape == (2, 2)
    assert result.matrix[0, 0] == 1
    assert result.matrix[0, 1] == -1
    assert result.matrix[1, 0] == 1
    assert result.matrix[1, 1] == 0


def test_discarded_ratings_are_not_stored():
    result = _build((1, 10, 5.0), (1, 20, 3.0))

    assert result.matrix.nnz == 1
    assert result.movie_ids == [10]


def test_indices_match_ids():
    result = _build((7, 300, 5.0), (3, 100, 1.0), (7, 100, 4.5))

    assert result.user_ids == [3, 7]
    assert result.movie_ids == [100, 300]
    m = result.matrix
    assert m[result.user_ids.index(3), result.movie_ids.index(100)] == -1
    assert m[result.user_ids.index(7), result.movie_ids.index(100)] == 1
    assert m[result.user_ids.index(7), result.movie_ids.index(300)] == 1


def test_last_rating_wins_for_duplicate_pair():
    result = _build((1, 10, 5.0), (1, 10, 1.0))

    assert result.matrix.shape == (1, 1)
    assert result.matrix[0, 0] == -1


def test_empty_input():
    result = _build()

    assert result.matrix.shape == (0, 0)
    assert result.user_ids == []
    assert result.movie_ids == []


def test_discarded_later_rating_keeps_previous_value():
    result = _build((1, 10, 5.0), (1, 10, 3.0))

    assert result.matrix[0, 0] == 1


def test_users_and_movies_without_kept_ratings_are_omitted():
    result = _build((1, 10, 5.0), (2, 20, 3.0))

    assert result.user_ids == [1]
    assert result.movie_ids == [10]
