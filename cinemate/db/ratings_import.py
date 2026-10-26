"""Idempotent import of an external ratings CSV (1-10 scale) into the database."""

import re
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemate.binarize import Binarizer
from cinemate.db.catalog import CatalogConflict, find_movie, import_from_tmdb, link, merge_movies
from cinemate.db.models import Movie, MovieExternalId, Rating, TmdbLookup, User
from cinemate.db.popularity import update_popularity
from cinemate.ratings_csv import CsvRow, movie_key, read_rows
from cinemate.tmdb import TmdbClient, TmdbSearchItem

_NON_WORD = re.compile(r"[\W_]+")
_SEARCH_TYPES = {
    "film": "movie",
    "video": "movie",
    "tvseries": "tv",
    "miniseries": "tv",
    "tvshow": "tv",
}


@dataclass(frozen=True)
class RatingsImportStats:
    movies_merged: int
    movies_added: int
    movies_ambiguous: int
    movies_skipped_no_title: int
    users_added: int
    ratings_added: int
    ratings_skipped: int
    popularity_updated: int
    matched_by_tmdb: int = 0
    matched_by_imdb: int = 0
    matched_by_kinopoisk: int = 0
    matched_by_search: int = 0
    unresolved: int = 0
    conflicts: int = 0


def normalize_title(title: str) -> str:
    """Casefold, drop punctuation and collapse whitespace."""
    return _NON_WORD.sub(" ", title.casefold()).strip()


def import_ratings_csv(
    session: Session,
    path: Path | str,
    binarizer: Binarizer,
    types: Collection[str] | None = None,
    client: TmdbClient | None = None,
    use_tmdb: bool = True,
) -> RatingsImportStats:
    """Import movies, users and ``+1``/``-1`` ratings from the ratings CSV at ``path``.

    Each movie of the file is matched in this order: TMDB pair (``tmdb_type``/``tmdb_id``), IMDb
    id (catalog, then TMDB ``/find``), Kinopoisk id (catalog, also ids of earlier imports), TMDB
    search by title and year. Otherwise it is merged into the single catalog movie with the same
    normalised title and year, else created without a TMDB pair (``unresolved``). Found movies
    get ``kinopoisk`` and ``imdb`` links; a link owned by another movie counts as a conflict.
    ``client`` is used for the TMDB steps; with ``use_tmdb=False`` the ``/find`` and search steps
    are skipped. TMDB answers of those steps are cached in ``tmdb_lookups``.
    Users are created (``is_synthetic``, no names) when they get at least one rating. Ratings the
    binarizer discards, ratings of skipped movies and existing (user, movie) pairs are not
    (re)added. With ``types`` only movies of those types (case-insensitive) are imported.
    """
    wanted = {t.strip().lower() for t in types} if types is not None else None
    movie_rows: dict[str, CsvRow] = {}
    scores: dict[tuple[int, str], int] = {}
    for row in read_rows(path):
        if wanted is not None and (row.type is None or row.type.lower() not in wanted):
            continue
        key = movie_key(row)
        first = movie_rows.get(key)
        movie_rows[key] = row if first is None else _fill_gaps(first, row)
        scores[(row.user_id, key)] = row.user_rating

    csv_linked: set[int] = set(
        session.scalars(
            select(MovieExternalId.movie_id).where(
                MovieExternalId.source.in_(("ratings_csv", "kinopoisk"))
            )
        )
    )
    index: dict[tuple[str, int], set[int]] = defaultdict(set)
    by_id: dict[int, Movie] = {}
    for m in session.scalars(select(Movie).where(Movie.year.is_not(None))):
        by_id[m.id] = m
        for name in (m.title, m.original_title):
            if name:
                index[(normalize_title(name), m.year)].add(m.id)

    lookup = _Lookup(session, client if use_tmdb else None)
    counts = {"tmdb": 0, "imdb": 0, "kinopoisk": 0, "search": 0, "conflicts": 0}
    movies: dict[str, Movie] = {}
    merged = added = ambiguous = no_title = unresolved = 0
    for key, row in movie_rows.items():
        movie, method = _match(session, client, lookup, row)
        if movie is not None:
            _fill_empty(movie, row)
            if movie.tmdb_id is None and lookup.enabled:
                _attach_pair(session, client, lookup, movie, row, counts)
        else:
            method = None
            candidates = _candidates(index, row)
            if len(candidates) == 1:
                found = by_id[next(iter(candidates))]
                if found.id not in csv_linked:
                    movie = found
                    merged += 1
            if movie is None:
                if candidates:
                    ambiguous += 1
                title = row.title_ru or row.title_original
                if title is None:
                    no_title += 1
                    continue
                movie = Movie(
                    tmdb_type=row.tmdb_type,
                    tmdb_id=row.tmdb_id,
                    external_ratings_id=row.kp_id,
                    title=title,
                    original_title=row.title_original,
                    year=row.year,
                    genres=list(row.genres),
                )
                session.add(movie)
                session.flush()
                added += 1
            else:
                _fill_empty(movie, row)
        if method is not None:
            counts[method] += 1
        for source, value in (("kinopoisk", row.kp_id), ("imdb", row.imdb_id)):
            if value is None:
                continue
            try:
                with session.begin_nested():
                    link(session, movie, source, value)
            except CatalogConflict:
                counts["conflicts"] += 1
        if row.kp_id is not None:
            csv_linked.add(movie.id)
            if movie.external_ratings_id is None:
                movie.external_ratings_id = row.kp_id
        if movie.tmdb_id is None:
            unresolved += 1
        movies[key] = movie
        if lookup.dirty:
            session.commit()  # keep cached TMDB answers if the run is interrupted
            lookup.dirty = False

    users = {
        u.external_ratings_id: u
        for u in session.scalars(select(User).where(User.external_ratings_id.is_not(None)))
    }
    session.flush()
    existing = {(u, m) for u, m in session.execute(select(Rating.user_id, Rating.movie_id))}

    users_added = ratings_added = ratings_skipped = 0
    for (ext_user, ext_movie), score in scores.items():
        movie = movies.get(ext_movie)
        value = binarizer.binarize(float(score), ext_user)
        if movie is None or value is None:
            ratings_skipped += 1
            continue
        user = users.get(ext_user)
        if user is None:
            user = User(external_ratings_id=ext_user, is_synthetic=True, pool="ru")
            session.add(user)
            session.flush()
            users[ext_user] = user
            users_added += 1
        if (user.id, movie.id) in existing:
            continue
        existing.add((user.id, movie.id))
        session.add(Rating(user_id=user.id, movie_id=movie.id, value=value))
        ratings_added += 1

    session.flush()
    popularity_updated = update_popularity(session)
    session.commit()
    return RatingsImportStats(
        merged,
        added,
        ambiguous,
        no_title,
        users_added,
        ratings_added,
        ratings_skipped,
        popularity_updated,
        matched_by_tmdb=counts["tmdb"],
        matched_by_imdb=counts["imdb"],
        matched_by_kinopoisk=counts["kinopoisk"],
        matched_by_search=counts["search"],
        unresolved=unresolved,
        conflicts=counts["conflicts"],
    )


class _Lookup:
    """TMDB ``find``/search with a DB cache (``tmdb_lookups``); ``None`` client = disabled."""

    def __init__(self, session: Session, client: TmdbClient | None) -> None:
        self.session = session
        self.client = client
        self.dirty = False

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def _cached(self, kind: str, query_key: str, fetch) -> tuple[str, int] | None:
        query_key = query_key[:256]
        row = self.session.get(TmdbLookup, (kind, query_key))
        if row is None:
            item = fetch()
            row = TmdbLookup(
                kind=kind,
                query_key=query_key,
                tmdb_type=item.tmdb_type if item else None,
                tmdb_id=item.tmdb_id if item else None,
            )
            self.session.add(row)
            self.dirty = True
        return (row.tmdb_type, row.tmdb_id) if row.tmdb_id is not None else None

    def find(self, imdb_id: str) -> tuple[str, int] | None:
        return self._cached("find", imdb_id, lambda: self.client.find_by_imdb(imdb_id))

    def search(self, row: CsvRow) -> tuple[str, int] | None:
        """The one TMDB title matching the row's title and year (at most a year off), if any."""
        if row.year is None:
            return None
        query = row.title_original or row.title_ru
        if query is None:
            return None
        wanted = _SEARCH_TYPES.get((row.type or "").lower())
        wanted_name = normalize_title(query)
        if not wanted_name:
            return None
        language = "en-US" if row.title_original else "ru-RU"
        key = f"{wanted or 'any'}|{wanted_name}|{row.year}"

        def fetch() -> TmdbSearchItem | None:
            matches = [
                item
                for item in self.client.search(query, language)
                if (wanted is None or item.tmdb_type == wanted)
                and item.year is not None
                and abs(item.year - row.year) <= 1
                and wanted_name
                in (normalize_title(item.title), normalize_title(item.original_title or ""))
            ]
            return matches[0] if len(matches) == 1 else None

        return self._cached("search", key, fetch)


def _match(
    session: Session, client: TmdbClient | None, lookup: _Lookup, row: CsvRow
) -> tuple[Movie | None, str | None]:
    """Steps 1-4 of the matching order; ``(movie, method)`` or ``(None, None)``."""
    if row.tmdb_id is not None:
        pair = (row.tmdb_type, row.tmdb_id)
        movie = find_movie(session, tmdb=pair)
        if movie is None and client is not None:
            try:
                movie = import_from_tmdb(session, client, *pair)
            except LookupError:
                movie = None
        if movie is not None:
            return movie, "tmdb"
    if row.imdb_id is not None:
        movie = find_movie(session, ids={"imdb": row.imdb_id})
        if movie is None and lookup.enabled:
            found = lookup.find(row.imdb_id)
            if found is not None:
                movie = import_from_tmdb(session, client, *found)
        if movie is not None:
            return movie, "imdb"
    if row.kp_id is not None:
        movie = find_movie(
            session, ids={"kinopoisk": str(row.kp_id), "ratings_csv": str(row.kp_id)}
        )
        if movie is not None:
            return movie, "kinopoisk"
    if lookup.enabled:
        found = lookup.search(row)
        if found is not None:
            return import_from_tmdb(session, client, *found), "search"
    return None, None


def _attach_pair(
    session: Session,
    client: TmdbClient,
    lookup: _Lookup,
    movie: Movie,
    row: CsvRow,
    counts: dict[str, int],
) -> None:
    """Give a catalog movie without a TMDB pair the pair found by search (cached)."""
    found = lookup.search(row)
    if found is None:
        return
    owner = find_movie(session, tmdb=found)
    if owner is not None:
        if owner.id != movie.id:
            counts["conflicts"] += 1  # the pair belongs to another movie: no re-linking
        return
    fresh = import_from_tmdb(session, client, *found)
    merge_movies(session, keep_id=movie.id, drop_id=fresh.id)
    session.refresh(movie)


def _candidates(index: dict[tuple[str, int], set[int]], row: CsvRow) -> set[int]:
    if not row.title_original or row.year is None:
        return set()
    return index.get((normalize_title(row.title_original), row.year), set())


def _fill_gaps(first: CsvRow, other: CsvRow) -> CsvRow:
    """``first`` with its empty movie fields taken from ``other``."""
    return CsvRow(
        user_id=first.user_id,
        user_rating=first.user_rating,
        kp_id=first.kp_id if first.kp_id is not None else other.kp_id,
        tmdb_type=first.tmdb_type or other.tmdb_type,
        tmdb_id=first.tmdb_id if first.tmdb_id is not None else other.tmdb_id,
        imdb_id=first.imdb_id or other.imdb_id,
        title_ru=first.title_ru or other.title_ru,
        title_original=first.title_original or other.title_original,
        type=first.type or other.type,
        year=first.year if first.year is not None else other.year,
        genres=first.genres or other.genres,
    )


def _fill_empty(movie: Movie, row: CsvRow) -> None:
    if movie.original_title is None and row.title_original:
        movie.original_title = row.title_original
    if movie.year is None and row.year is not None:
        movie.year = row.year
    if not movie.genres and row.genres:
        movie.genres = list(row.genres)
