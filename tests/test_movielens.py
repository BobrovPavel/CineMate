from pathlib import Path

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
        Movie(1, "Toy Story", 1995, ["Adventure", "Animation"]),
        Movie(2, "No Year Movie", None, ["Drama"]),
        Movie(3, "Hello, World", 2001, []),
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
        "movieId,imdbId,tmdbId\n1,0114709,862\n2,0113497,\n3,1234567,15602\n",
    )
    assert list(parse_links(path)) == [
        Link(1, "tt0114709", 862),
        Link(2, "tt0113497", None),
        Link(3, "tt1234567", 15602),
    ]
