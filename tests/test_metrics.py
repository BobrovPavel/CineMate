import pytest

from cinemate.evaluation.metrics import (
    coverage,
    mean_popularity,
    precision_at_k,
    recall_at_k,
    split_ratings,
)
from cinemate.movielens import Rating


def _ratings() -> list[Rating]:
    out = [Rating(u, m, 4.0) for u in (1, 2) for m in range(1, 11)]
    out += [Rating(3, m, 5.0) for m in range(1, 5)]  # too few ratings
    return out


def test_precision_and_recall_known_values():
    rec = [1, 2, 3, 4]
    rel = {2, 4, 9}
    assert precision_at_k(rec, rel, 4) == 0.5
    assert recall_at_k(rec, rel, 4) == pytest.approx(2 / 3)
    assert precision_at_k(rec, rel, 2) == 0.5
    assert recall_at_k(rec, rel, 2) == pytest.approx(1 / 3)


def test_k_larger_than_list():
    assert precision_at_k([1], {1}, 5) == 0.2
    assert recall_at_k([1], {1}, 5) == 1.0


def test_empty_inputs_do_not_divide_by_zero():
    assert precision_at_k([], {1}, 3) == 0.0
    assert precision_at_k([1], {1}, 0) == 0.0
    assert recall_at_k([1, 2], set(), 2) == 0.0
    assert recall_at_k([1], {1}, 0) == 0.0
    assert coverage([], 10) == 0.0
    assert coverage([[1]], 0) == 0.0
    assert mean_popularity([], {1: 5.0}) == 0.0


def test_coverage():
    assert coverage([[1, 2], [2, 3]], 6) == 0.5


def test_mean_popularity():
    assert mean_popularity([1, 2, 3], {1: 10, 2: 20}) == 10.0


def test_split_is_deterministic_and_disjoint():
    a = split_ratings(_ratings(), 0.2, seed=1)
    b = split_ratings(_ratings(), 0.2, seed=1)
    assert a == b
    train, test = a
    assert not set(train) & set(test)
    assert len(train) + len(test) == len(_ratings())
    assert sum(r.user_id == 1 for r in test) == 2
    assert split_ratings(_ratings(), 0.2, seed=2) != a


def test_split_small_users_have_empty_test():
    train, test = split_ratings(_ratings())
    assert all(r.user_id != 3 for r in test)
    assert sum(r.user_id == 3 for r in train) == 4


def test_split_zero_fraction_and_validation():
    train, test = split_ratings(_ratings(), 0.0)
    assert test == [] and len(train) == len(_ratings())
    with pytest.raises(ValueError):
        split_ratings(_ratings(), 1.0)
