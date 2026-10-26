import pytest

from cinemate.movielens import Rating
from cinemate.ratings_csv import CsvRow, load_ratings, read_rows

HEADER = "user_id,kp_id,title_ru,title_original,type,year,genres,kp_rating,user_rating\n"


def _write(tmp_path, body, header=HEADER):
    path = tmp_path / "ratings.csv"
    path.write_text(header + body, encoding="utf-8")
    return path


def test_read_rows_parses_fields(tmp_path):
    path = _write(
        tmp_path,
        '1,10,Холодец,,MiniSeries,2025,"комедия, драма",,9\n2,11,,Orig,Film,,,7.5,3\n',
    )
    rows = list(read_rows(path))
    assert rows[0] == CsvRow(
        1,
        9,
        kp_id=10,
        title_ru="Холодец",
        type="MiniSeries",
        year=2025,
        genres=("комедия", "драма"),
    )
    assert rows[1] == CsvRow(2, 3, kp_id=11, title_original="Orig", type="Film", kp_rating=7.5)


def test_read_rows_ignores_extra_columns_and_order(tmp_path):
    path = _write(tmp_path, "9,5,1,junk\n", header="user_rating,kp_id,user_id,extra\n")
    assert list(read_rows(path)) == [CsvRow(user_id=1, kp_id=5, user_rating=9)]


@pytest.mark.parametrize("column", ["user_id", "user_rating"])
def test_missing_required_column(tmp_path, column):
    cols = [c for c in ("user_id", "kp_id", "user_rating") if c != column]
    path = _write(tmp_path, "1,2\n", header=",".join(cols) + "\n")
    with pytest.raises(ValueError, match=column):
        list(read_rows(path))


def test_missing_movie_id_columns(tmp_path):
    path = _write(tmp_path, "1,2\n", header="user_id,user_rating\n")
    with pytest.raises(ValueError, match="kp_id, tmdb_id or imdb_id"):
        list(read_rows(path))


def test_movie_id_is_a_deprecated_synonym_of_kp_id(tmp_path):
    path = _write(tmp_path, "1,5,9\n", header="user_id,movie_id,user_rating\n")
    with pytest.warns(UserWarning, match="movie_id"):
        rows = list(read_rows(path))
    assert rows == [CsvRow(user_id=1, kp_id=5, user_rating=9)]


def test_new_id_columns(tmp_path):
    path = _write(
        tmp_path,
        "1,,TV,1399,tt0944947,8\n2,7,movie,5,,6\n3,,,,tt1,4\n",
        header="user_id,kp_id,tmdb_type,tmdb_id,imdb_id,user_rating\n",
    )
    rows = list(read_rows(path))
    assert (rows[0].kp_id, rows[0].tmdb_type, rows[0].tmdb_id, rows[0].imdb_id) == (
        None,
        "tv",
        1399,
        "tt0944947",
    )
    assert (rows[1].kp_id, rows[1].tmdb_type, rows[1].tmdb_id) == (7, "movie", 5)
    assert rows[2].imdb_id == "tt1"


@pytest.mark.parametrize(
    "row",
    [
        "1,,movie,,,5",  # tmdb_type without tmdb_id
        "1,,,10,,5",  # tmdb_id without tmdb_type
        "1,,anime,10,,5",  # bad tmdb_type
        "1,,,,123,5",  # bad imdb_id
        "1,,,,,5",  # no movie id at all
    ],
)
def test_invalid_id_columns_report_line(tmp_path, row):
    path = _write(
        tmp_path,
        row + "\n",
        header="user_id,kp_id,tmdb_type,tmdb_id,imdb_id,user_rating\n",
    )
    with pytest.raises(ValueError, match="line 2"):
        list(read_rows(path))


def test_load_ratings_key_prefers_tmdb_then_imdb_then_kp(tmp_path):
    path = _write(
        tmp_path,
        "1,7,movie,5,tt1,9\n2,,,,tt1,8\n3,7,,,,7\n",
        header="user_id,kp_id,tmdb_type,tmdb_id,imdb_id,user_rating\n",
    )
    assert [r.movie_id for r in load_ratings(path)] == ["tmdb:movie:5", "imdb:tt1", "kp:7"]


@pytest.mark.parametrize("rating", ["0", "11", "7.5", "x", ""])
def test_invalid_user_rating_reports_line(tmp_path, rating):
    path = _write(tmp_path, f"1,10,,,Film,2020,,,8\n1,11,,,Film,2020,,,{rating}\n")
    with pytest.raises(ValueError, match="line 3"):
        list(read_rows(path))


@pytest.mark.parametrize("row", ["a,1,,,,,,,5", "1,b,,,,,,,5", "1,1,,,,abc,,,5", "1,1,,,,,,abc,5"])
def test_invalid_row_reports_line(tmp_path, row):
    path = _write(tmp_path, row + "\n")
    with pytest.raises(ValueError, match="line 2"):
        list(read_rows(path))


def test_load_ratings_basic(tmp_path):
    path = _write(tmp_path, "1,10,,,Film,,,,9\n1,11,,,,,,,4\n")
    assert load_ratings(path) == [Rating(1, "kp:10", 9.0), Rating(1, "kp:11", 4.0)]


def test_load_ratings_filters_types_case_insensitive(tmp_path):
    path = _write(tmp_path, "1,10,,,Film,,,,9\n1,11,,,TvSeries,,,,4\n1,12,,,,,,,5\n")
    assert load_ratings(path, ["film"]) == [Rating(1, "kp:10", 9.0)]
    assert load_ratings(path, ["Film", "TVSERIES"]) == [
        Rating(1, "kp:10", 9.0),
        Rating(1, "kp:11", 4.0),
    ]


def test_last_duplicate_wins(tmp_path):
    path = _write(tmp_path, "1,10,,,,,,,3\n1,10,,,,,,,8\n")
    assert load_ratings(path) == [Rating(1, "kp:10", 8.0)]


def test_empty_result_raises(tmp_path):
    with pytest.raises(ValueError, match="no ratings"):
        load_ratings(_write(tmp_path, ""))
    path = _write(tmp_path, "1,10,,,Film,,,,9\n")
    with pytest.raises(ValueError, match="no ratings"):
        load_ratings(path, ["TvSeries"])
