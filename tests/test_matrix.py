from scipy.sparse import csr_matrix

from cinemate.binarize import MovieLensBinarizer
from cinemate.movielens import Rating
from cinemate.recommender.matrix import build_matrix

BIN = MovieLensBinarizer()


def test_like_and_dislike_values():
    result = build_matrix([Rating(1, 10, 5.0), Rating(1, 20, 1.0)], BIN)
    assert isinstance(result.matrix, csr_matrix)
    assert result.matrix.shape == (1, 2)
    assert result.matrix[0, 0] == 1
    assert result.matrix[0, 1] == -1


def test_discarded_ratings_are_skipped():
    result = build_matrix([Rating(1, 10, 5.0), Rating(1, 20, 3.0), Rating(2, 30, 3.0)], BIN)
    assert result.user_ids == [1]
    assert result.movie_ids == [10]
    assert result.matrix.nnz == 1


def test_indices_match_ids():
    ratings = [Rating(7, 300, 5.0), Rating(3, 100, 1.0), Rating(7, 100, 4.0)]
    result = build_matrix(ratings, BIN)
    assert result.user_ids == [3, 7]
    assert result.movie_ids == [100, 300]
    assert result.matrix.toarray().tolist() == [[-1, 0], [1, 1]]


def test_last_rating_wins_for_duplicate_pair():
    result = build_matrix([Rating(1, 10, 5.0), Rating(1, 10, 1.0)], BIN)
    assert result.matrix.shape == (1, 1)
    assert result.matrix[0, 0] == -1


def test_empty_input():
    result = build_matrix([], BIN)
    assert result.matrix.shape == (0, 0)
    assert result.user_ids == []
    assert result.movie_ids == []


def test_discarded_later_rating_keeps_previous_value():
    result = build_matrix([Rating(1, 10, 5.0), Rating(1, 10, 3.0)], BIN)
    assert result.matrix[0, 0] == 1


def test_users_and_movies_without_kept_ratings_are_omitted():
    result = build_matrix([Rating(1, 10, 5.0), Rating(2, 20, 3.0)], BIN)
    assert result.user_ids == [1]
    assert result.movie_ids == [10]


def test_matrix_from_values_builds_from_binarized_triples():
    from cinemate.recommender.matrix import matrix_from_values

    result = matrix_from_values([(2, 5, -1), (1, 5, 1), (1, 3, 1), (1, 3, -1)])
    assert result.user_ids == [1, 2]
    assert result.movie_ids == [3, 5]
    assert result.matrix.toarray().tolist() == [[-1, 1], [0, -1]]
