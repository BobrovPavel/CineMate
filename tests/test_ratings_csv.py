import pytest

from cinemate.movielens import Rating
from cinemate.ratings_csv import CsvRow, load_ratings, read_rows

HEADER = "user_id,movie_id,title_ru,title_original,type,year,genres,kp_rating,user_rating\n"


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
        1, 10, 9, "Холодец", None, "MiniSeries", 2025, ("комедия", "драма"), None
    )
    assert rows[1] == CsvRow(2, 11, 3, None, "Orig", "Film", None, (), 7.5)


def test_read_rows_ignores_extra_columns_and_order(tmp_path):
    path = _write(tmp_path, "9,5,1,junk\n", header="user_rating,movie_id,user_id,extra\n")
    assert list(read_rows(path)) == [CsvRow(user_id=1, movie_id=5, user_rating=9)]


@pytest.mark.parametrize("column", ["user_id", "movie_id", "user_rating"])
def test_missing_required_column(tmp_path, column):
    cols = [c for c in ("user_id", "movie_id", "user_rating") if c != column]
    path = _write(tmp_path, "1,2\n", header=",".join(cols) + "\n")
    with pytest.raises(ValueError, match=column):
        list(read_rows(path))


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
    assert load_ratings(path) == [Rating(1, 10, 9.0), Rating(1, 11, 4.0)]


def test_load_ratings_filters_types_case_insensitive(tmp_path):
    path = _write(tmp_path, "1,10,,,Film,,,,9\n1,11,,,TvSeries,,,,4\n1,12,,,,,,,5\n")
    assert load_ratings(path, ["film"]) == [Rating(1, 10, 9.0)]
    assert load_ratings(path, ["Film", "TVSERIES"]) == [Rating(1, 10, 9.0), Rating(1, 11, 4.0)]


def test_last_duplicate_wins(tmp_path):
    path = _write(tmp_path, "1,10,,,,,,,3\n1,10,,,,,,,8\n")
    assert load_ratings(path) == [Rating(1, 10, 8.0)]


def test_empty_result_raises(tmp_path):
    with pytest.raises(ValueError, match="no ratings"):
        load_ratings(_write(tmp_path, ""))
    path = _write(tmp_path, "1,10,,,Film,,,,9\n")
    with pytest.raises(ValueError, match="no ratings"):
        load_ratings(path, ["TvSeries"])
