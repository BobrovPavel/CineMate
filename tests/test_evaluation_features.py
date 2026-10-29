from cinemate.evaluation.features import movielens_features


def test_movielens_features_translate_genres_and_keep_year(tmp_path):
    path = tmp_path / "movies.csv"
    path.write_text(
        "movieId,title,genres\n"
        "1,Toy Story (1995),Adventure|Animation|Children|IMAX\n"
        "2,Nothing (2001),(no genres listed)\n",
        encoding="utf-8",
    )
    features = movielens_features(path)
    assert features[1].genres == (12, 16, 10751)
    assert features[1].year == 1995
    assert features[2].genres == ()
