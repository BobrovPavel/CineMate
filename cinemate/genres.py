"""One genre dictionary: TMDB genre ids, and tables mapping older genre names onto them.

``GENRES`` is the static content of the ``genres`` table (``/genre/movie/list`` plus the TV
genres that have no movie counterpart, English and Russian). Composite TV genres are split into
movie ones; MovieLens and Kinopoisk names are translated by ``legacy_genre_ids``.
"""

from collections.abc import Iterable
from typing import NamedTuple


class GenreInfo(NamedTuple):
    id: int
    name_en: str
    name_ru: str


GENRES: tuple[GenreInfo, ...] = (
    GenreInfo(28, "Action", "боевик"),
    GenreInfo(12, "Adventure", "приключения"),
    GenreInfo(16, "Animation", "мультфильм"),
    GenreInfo(35, "Comedy", "комедия"),
    GenreInfo(80, "Crime", "криминал"),
    GenreInfo(99, "Documentary", "документальный"),
    GenreInfo(18, "Drama", "драма"),
    GenreInfo(10751, "Family", "семейный"),
    GenreInfo(14, "Fantasy", "фэнтези"),
    GenreInfo(36, "History", "история"),
    GenreInfo(27, "Horror", "ужасы"),
    GenreInfo(10402, "Music", "музыка"),
    GenreInfo(9648, "Mystery", "детектив"),
    GenreInfo(10749, "Romance", "мелодрама"),
    GenreInfo(878, "Science Fiction", "фантастика"),
    GenreInfo(10770, "TV Movie", "телевизионный фильм"),
    GenreInfo(53, "Thriller", "триллер"),
    GenreInfo(10752, "War", "военный"),
    GenreInfo(37, "Western", "вестерн"),
    # TV genres without a movie counterpart
    GenreInfo(10762, "Kids", "детский"),
    GenreInfo(10763, "News", "новости"),
    GenreInfo(10764, "Reality", "реалити-шоу"),
    GenreInfo(10766, "Soap", "мыльная опера"),
    GenreInfo(10767, "Talk", "ток-шоу"),
)
GENRE_IDS = frozenset(g.id for g in GENRES)

# composite TV genres (`/genre/tv/list`) -> movie genres
TV_SPLIT: dict[int, tuple[int, ...]] = {
    10759: (28, 12),  # Action & Adventure
    10765: (878, 14),  # Sci-Fi & Fantasy
    10768: (10752,),  # War & Politics
}
_TV_SPLIT_NAMES = {
    "action & adventure": TV_SPLIT[10759],
    "sci-fi & fantasy": TV_SPLIT[10765],
    "war & politics": TV_SPLIT[10768],
}

# MovieLens names; "IMAX" and "(no genres listed)" are dropped (absent here)
MOVIELENS_GENRES: dict[str, tuple[int, ...]] = {
    "action": (28,),
    "adventure": (12,),
    "animation": (16,),
    "children": (10751,),
    "comedy": (35,),
    "crime": (80,),
    "documentary": (99,),
    "drama": (18,),
    "fantasy": (14,),
    "horror": (27,),
    "musical": (10402,),
    "mystery": (9648,),
    "romance": (10749,),
    "sci-fi": (878,),
    "thriller": (53,),
    "war": (10752,),
    "western": (37,),
    "film-noir": (80,),
}

# Kinopoisk names (Russian, lower case); names absent here ("биография", "спорт",
# "короткометражка", ...) are dropped
KINOPOISK_GENRES: dict[str, tuple[int, ...]] = {
    "боевик": (28,),
    "приключения": (12,),
    "мультфильм": (16,),
    "аниме": (16,),
    "семейный": (10751,),
    "детский": (10751,),
    "комедия": (35,),
    "криминал": (80,),
    "документальный": (99,),
    "драма": (18,),
    "фэнтези": (14,),
    "ужасы": (27,),
    "мюзикл": (10402,),
    "музыка": (10402,),
    "детектив": (9648,),
    "мелодрама": (10749,),
    "фантастика": (878,),
    "триллер": (53,),
    "военный": (10752,),
    "вестерн": (37,),
    "история": (36,),
    "реальное тв": (10764,),
    "ток-шоу": (10767,),
    "новости": (10763,),
}


def _legacy_table() -> dict[str, tuple[int, ...]]:
    table: dict[str, tuple[int, ...]] = dict(_TV_SPLIT_NAMES)
    table.update(MOVIELENS_GENRES)
    table.update(KINOPOISK_GENRES)
    for genre in GENRES:  # TMDB names already stored in the old column
        table.setdefault(genre.name_en.casefold(), (genre.id,))
        table.setdefault(genre.name_ru.casefold(), (genre.id,))
    return table


_LEGACY = _legacy_table()


def legacy_genre_ids(names: Iterable[str]) -> tuple[list[int], list[str]]:
    """Genre ids for old-style names (MovieLens, Kinopoisk, TMDB), plus the dropped names.

    Ids are unique and in order of appearance.
    """
    ids: list[int] = []
    dropped: list[str] = []
    for name in names:
        found = _LEGACY.get(str(name).strip().casefold())
        if found is None:
            dropped.append(name)
            continue
        ids.extend(i for i in found if i not in ids)
    return ids, dropped


def tmdb_genre_ids(raw_ids: Iterable[int]) -> list[int]:
    """Movie-dictionary ids for TMDB genre ids: composite TV genres split, unknown ids dropped."""
    ids: list[int] = []
    for raw in raw_ids:
        for genre_id in TV_SPLIT.get(raw, (raw,)):
            if genre_id in GENRE_IDS and genre_id not in ids:
                ids.append(genre_id)
    return ids
