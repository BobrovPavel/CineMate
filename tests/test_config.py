import pytest

from cinemate.config import RecommenderSettings


def test_defaults():
    s = RecommenderSettings()
    assert (s.k, s.lam, s.min_overlap, s.pop_penalty) == (40, 40.0, 3, 1.0)


def test_from_env_empty_or_missing_gives_defaults():
    assert RecommenderSettings.from_env({}) == RecommenderSettings()
    assert RecommenderSettings.from_env({"REC_K": "", "REC_LAMBDA": "  "}) == RecommenderSettings()


def test_from_env_reads_all_variables():
    env = {
        "REC_K": "10",
        "REC_LAMBDA": "2.5",
        "REC_MIN_OVERLAP": "4",
        "REC_POP_PENALTY": "0",
        "REC_MIN_USER_RATINGS": "20",
        "REC_FALLBACK_POOL_FACTOR": "1",
    }
    assert RecommenderSettings.from_env(env) == RecommenderSettings(10, 2.5, 4, 0.0, 20, 1)


def test_from_env_reads_os_environ(monkeypatch):
    monkeypatch.setenv("REC_K", "7")
    assert RecommenderSettings.from_env().k == 7


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REC_K", "abc"),
        ("REC_K", "0"),
        ("REC_K", "2.5"),
        ("REC_LAMBDA", "x"),
        ("REC_LAMBDA", "-1"),
        ("REC_LAMBDA", "nan"),
        ("REC_MIN_OVERLAP", "zero"),
        ("REC_MIN_OVERLAP", "0"),
        ("REC_POP_PENALTY", "y"),
        ("REC_POP_PENALTY", "-0.1"),
        ("REC_POP_PENALTY", "nan"),
        ("REC_MIN_USER_RATINGS", "abc"),
        ("REC_MIN_USER_RATINGS", "0"),
        ("REC_MIN_USER_RATINGS", "2.5"),
        ("REC_FALLBACK_POOL_FACTOR", "x"),
        ("REC_FALLBACK_POOL_FACTOR", "0"),
        ("REC_FALLBACK_POOL_FACTOR", "-1"),
    ],
)
def test_from_env_invalid_names_variable(name, value):
    with pytest.raises(ValueError, match=name):
        RecommenderSettings.from_env({name: value})


def test_nan_is_rejected_even_for_lenient_check():
    with pytest.raises(ValueError, match="REC_LAMBDA"):
        RecommenderSettings.from_env({"REC_LAMBDA": "NaN"})


def test_new_settings_defaults():
    settings = RecommenderSettings()
    assert (settings.min_user_ratings, settings.fallback_pool_factor) == (10, 2)
