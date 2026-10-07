import pytest

from cinemate.binarize import Binarizer, MovieLensBinarizer


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.5, -1),
        (2.5, -1),
        (3.0, None),
        (3.5, 1),
        (5.0, 1),
    ],
)
def test_default_thresholds(score: float, expected: int | None) -> None:
    assert MovieLensBinarizer().binarize(score) == expected


@pytest.mark.parametrize(
    ("score", "expected"),
    [(2.0, -1), (2.5, None), (3.5, None), (4.0, 1), (4.5, 1)],
)
def test_custom_thresholds(score: float, expected: int | None) -> None:
    assert MovieLensBinarizer(like_threshold=4.0, dislike_threshold=2.0).binarize(score) == expected


def test_satisfies_protocol() -> None:
    binarizer: Binarizer = MovieLensBinarizer()
    assert binarizer.binarize(4.0) == 1
