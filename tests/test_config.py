import pytest

from cinemate.config import RecommenderSettings


def test_defaults():
    s = RecommenderSettings()
    assert (s.k, s.lam, s.min_overlap, s.pop_penalty) == (150, 40.0, 1, 0.75)
    assert s.significance == 0


def test_from_env_empty_or_missing_gives_defaults():
    assert RecommenderSettings.from_env({}) == RecommenderSettings()
    assert RecommenderSettings.from_env({"REC_K": "", "REC_LAMBDA": "  "}) == RecommenderSettings()


def test_from_env_reads_all_variables():
    env = {
        "REC_K": "10",
        "REC_LAMBDA": "2.5",
        "REC_MIN_OVERLAP": "4",
        "REC_POP_PENALTY": "0",
        "REC_SIGNIFICANCE": "5",
        "REC_MIN_USER_RATINGS": "20",
        "REC_FALLBACK_POOL_FACTOR": "1",
    }
    assert RecommenderSettings.from_env(env) == RecommenderSettings(10, 2.5, 4, 0.0, 20, 1, 5)


def test_previous_k_is_still_accepted():
    assert RecommenderSettings.from_env({"REC_K": "60"}).k == 60


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
        ("REC_SIGNIFICANCE", "x"),
        ("REC_SIGNIFICANCE", "-1"),
        ("REC_SIGNIFICANCE", "2.5"),
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
    assert (settings.min_user_ratings, settings.fallback_pool_factor) == (5, 1)


def test_min_overlap_default_is_one_and_env_override_works():
    assert RecommenderSettings().min_overlap == 1
    assert RecommenderSettings.from_env({"REC_MIN_OVERLAP": "3"}).min_overlap == 3


def test_min_overlap_default_gives_neighbors_to_new_user_but_three_does_not():
    from scipy.sparse import csr_matrix

    from cinemate.recommender.similarity import find_neighbors

    m = csr_matrix([[1, 1, 0, 0], [1, 1, 1, 0], [0, 0, 1, 1]], dtype="int8")
    overlap = RecommenderSettings().min_overlap
    assert [i for i, _ in find_neighbors(m, 0, min_overlap=overlap)] == [1]
    assert find_neighbors(m, 0, min_overlap=3) == []


def test_tune_min_overlap_default_grid():
    from cinemate.cli import build_parser

    assert build_parser().parse_args(["tune"]).min_overlap == "1,2,3"


def test_strategy_constants_match_settings_defaults():
    from cinemate.recommender.fallback import DEFAULT_POOL_FACTOR
    from cinemate.recommender.strategy import MIN_USER_RATINGS

    settings = RecommenderSettings()
    assert settings.min_user_ratings == MIN_USER_RATINGS
    assert settings.fallback_pool_factor == DEFAULT_POOL_FACTOR


def test_blend_full_at_default_off_and_env():
    assert RecommenderSettings().blend_full_at == 0.0
    assert RecommenderSettings.from_env({"REC_BLEND_FULL_AT": "30"}).blend_full_at == 30.0
    assert RecommenderSettings.from_env({"REC_BLEND_FULL_AT": "0"}).blend_full_at == 0.0


@pytest.mark.parametrize("value", ["-1", "abc", "nan"])
def test_blend_full_at_invalid(value):
    with pytest.raises(ValueError, match="REC_BLEND_FULL_AT"):
        RecommenderSettings.from_env({"REC_BLEND_FULL_AT": value})
