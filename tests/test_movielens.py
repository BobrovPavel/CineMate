from pathlib import Path

import pytest

from cinemate.movielens import Link, Movie, Rating, parse_links, parse_movies, parse_ratings


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_movies(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "movies.csv",
        "movieId,title,genres\n"
        "1,Toy Story (1995),Adventure|Animation\n"
        "2,No Year Movie,Drama\n"
        '3,"Hello, World (2001)",(no genres listed)\n',
    )
    assert list(parse_movies(path)) == [
        Movie(1, "Toy Story", 1995, ("Adventure", "Animation")),
        Movie(2, "No Year Movie", None, ("Drama",)),
        Movie(3, "Hello, World", 2001, ()),
    ]


def test_parse_ratings(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ratings.csv",
        "userId,movieId,rating,timestamp\n1,1,4.0,964982703\n2,3,0.5,964981247\n",
    )
    assert list(parse_ratings(path)) == [Rating(1, 1, 4.0), Rating(2, 3, 0.5)]


def test_parse_links(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "links.csv",
        "movieId,imdbId,tmdbId\n1,0114709,862\n2,0113497,\n3,1234567,15602\n4,12,7\n5,,8\n",
    )
    assert list(parse_links(path)) == [
        Link(1, "tt0114709", 862),
        Link(2, "tt0113497", None),
        Link(3, "tt1234567", 15602),
        Link(4, "tt0000012", 7),
        Link(5, None, 8),
    ]


def test_parse_movies_title_with_extra_parentheses(tmp_path: Path) -> None:
    path = _write(tmp_path, "movies.csv", "movieId,title,genres\n1,Foo (a.k.a. Bar) (1999),Drama\n")
    assert list(parse_movies(path)) == [Movie(1, "Foo", 1999, ("Drama",), "a.k.a. Bar")]


@pytest.mark.parametrize(
    ("raw", "title", "year", "alt"),
    [
        ("Blair Witch Project, The (1999)", "The Blair Witch Project", 1999, None),
        ("Ace Ventura: When Nature Calls (1995)", "Ace Ventura: When Nature Calls", 1995, None),
        ("Home Alone (1990)", "Home Alone", 1990, None),
        ("Avventura, L' (1960)", "L'Avventura", 1960, None),
        (
            "City of Lost Children, The (Cité des enfants perdus, La) (1995)",
            "The City of Lost Children",
            1995,
            "La Cité des enfants perdus",
        ),
        (
            "Good, the Bad and the Ugly, The (1966)",
            "The Good, the Bad and the Ugly",
            1966,
            None,
        ),
        ("Heaven & Earth (Tian yu di) (1993)", "Heaven & Earth", 1993, "Tian yu di"),
        ("Foo (First) (Second) (2000)", "Foo", 2000, "First"),
        ("Foo (Bar) Baz (2000)", "Foo (Bar) Baz", 2000, None),
        ("Foo () (2000)", "Foo ()", 2000, None),
        ("Mystery, the (2000)", "the Mystery", 2000, None),
        ("Movie, The", "Movie, The", None, None),
        ("  No Year  ", "No Year", None, None),
        ("The (2000)", "The", 2000, None),
        ("", "", None, None),
    ],
)
def test_title_normalization(tmp_path: Path, raw: str, title: str, year: int | None, alt) -> None:
    path = _write(tmp_path, "movies.csv", f'movieId,title,genres\n1,"{raw}",Drama\n')
    assert list(parse_movies(path)) == [Movie(1, title, year, ("Drama",), alt)]
