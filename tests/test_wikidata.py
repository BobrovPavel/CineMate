import json

import pytest

from cinemate.cli import main
from cinemate.wikidata import (
    WikidataEntry,
    WikidataError,
    build_entries,
    fetch_mapping,
    load_mapping,
    parse_bindings,
    save_mapping,
)


def _b(kp, movie=None, tv=None, imdb=None):
    out = {"kp": {"value": str(kp)}}
    if movie:
        out["tmdbMovie"] = {"value": str(movie)}
    if tv:
        out["tmdbTv"] = {"value": str(tv)}
    if imdb:
        out["imdb"] = {"value": imdb}
    return out


def _body(bindings):
    return json.dumps({"results": {"bindings": bindings}}).encode()


def test_parse_and_drop_ambiguous():
    bindings = [
        _b(1, movie=10, imdb="tt1"),
        _b(2, movie=20),
        _b(2, movie=21),  # kp 2 has two pairs
        _b(3, tv=30),
        _b(3, movie=30),  # movie and tv: two pairs
        _b(4, movie=40),
        _b(5, movie=40),  # one pair for two kp ids
        _b(6, imdb="tt6"),
        _b(6, imdb="tt7"),  # ambiguous imdb, no pair: nothing left
        _b(7, tv=70, imdb="tt8"),
        {"kp": {"value": "abc"}},
    ]
    result = build_entries(*parse_bindings(bindings))
    assert result.entries == {
        1: WikidataEntry("movie", 10, "tt1"),
        7: WikidataEntry("tv", 70, "tt8"),
    }
    assert result.dropped == 4


def test_save_and_load_roundtrip(tmp_path):
    entries = {1: WikidataEntry("movie", 10, "tt1"), 2: WikidataEntry(None, None, "tt2")}
    path = tmp_path / "out" / "w.csv"
    save_mapping(path, entries)
    assert path.read_text(encoding="utf-8").splitlines()[0] == "kp_id,tmdb_type,tmdb_id,imdb_id"
    assert load_mapping(path) == entries


def test_fetch_pages_and_user_agent():
    pages = [[_b(1, movie=10), _b(2, tv=20)], [_b(3, movie=30)]]
    seen = []

    def http_get(url, headers):
        seen.append(headers)
        return 200, _body(pages[len(seen) - 1]), None

    sleeps = []
    result = fetch_mapping(http_get, sleeps.append, page_size=2, pause=1.0)
    assert sorted(result.entries) == [1, 2, 3]
    assert len(seen) == 2 and sleeps == [1.0]
    assert "github.com/BobrovPavel/CineMate" in seen[0]["User-Agent"]


def test_fetch_retries_429_and_5xx():
    answers = iter([(429, b"", 3.0), (503, b"", None), (200, _body([_b(1, movie=1)]), None)])
    sleeps = []
    result = fetch_mapping(lambda url, h: next(answers), sleeps.append, page_size=5)
    assert list(result.entries) == [1]
    assert len(sleeps) == 2


def test_fetch_errors():
    with pytest.raises(WikidataError):
        fetch_mapping(lambda url, h: (404, b"", None), lambda s: None)
    with pytest.raises(WikidataError):
        fetch_mapping(lambda url, h: (200, b"nope", None), lambda s: None)
    answers = iter([(500, b"", None)] * 10)
    with pytest.raises(WikidataError):
        fetch_mapping(lambda url, h: next(answers), lambda s: None)


def test_cli_fetch_writes_file(tmp_path, monkeypatch, capsys):
    from cinemate import cli
    from cinemate.wikidata import FetchResult

    monkeypatch.setattr(
        cli, "fetch_mapping", lambda **kw: FetchResult({5: WikidataEntry("tv", 9, None)}, 2)
    )
    out = tmp_path / "w.csv"
    assert main(["fetch-wikidata-kinopoisk", "--out", str(out)]) == 0
    assert load_mapping(out) == {5: WikidataEntry("tv", 9, None)}
    assert "written: 1, ambiguous dropped: 2" in capsys.readouterr().out
