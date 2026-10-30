"""Pydantic request/response models of the HTTP API."""

from typing import Literal

from pydantic import BaseModel, Field, PositiveInt, StrictInt, field_validator


class SessionOut(BaseModel):
    user_id: int
    pool: str


class MeOut(BaseModel):
    user_id: int
    pool: str
    rated_count: int


class ProfileItem(BaseModel):
    movie_id: int
    title: str
    title_ru: str | None
    year: int | None
    poster_path: str | None
    value: int


class OnboardingCard(BaseModel):
    movie_id: int
    title: str
    title_ru: str | None
    year: int | None
    poster_path: str | None
    genres: list[str]


class MovieCard(BaseModel):
    id: int
    title: str
    title_ru: str | None
    original_title: str | None
    year: int | None
    overview: str | None
    poster_path: str | None
    genres: list[str]
    runtime: int | None


class PersonOut(BaseModel):
    id: int
    name: str


class CastOut(BaseModel):
    id: int
    name: str
    character: str | None
    profile_path: str | None


class RatingSourceOut(BaseModel):
    source: str
    label: str
    value: float
    scale: Literal["10", "%"]
    votes: int | None
    url: str | None


class MovieDetail(MovieCard):
    """The movie page: the card plus titles by language, credits, ratings and the user's reaction.

    ``countries`` are ISO 3166-1 codes (the frontend names them); ``budget`` and ``revenue``
    are set only for movies and only when above 0.
    """

    display_title: str
    second_title: str | None
    type: Literal["movie", "tv"]
    number_of_seasons: int | None
    number_of_episodes: int | None
    tagline: str | None
    certification: str | None
    keywords: list[str]
    studios: list[str]
    countries: list[str]
    collection: str | None
    budget: int | None
    revenue: int | None
    directors: list[PersonOut]
    writers: list[PersonOut]
    producers: list[PersonOut]
    composers: list[PersonOut]
    creators: list[PersonOut]
    cast: list[CastOut]
    ratings: list[RatingSourceOut]
    user_value: Literal[1, -1] | None
    user_mark: Literal["not_seen", "watched", "not_interested"] | None


class BecauseOf(BaseModel):
    movie_id: int
    title: str
    title_ru: str | None


class BecauseTaste(BaseModel):
    kind: str
    id: str
    name: str


class RecommendationItem(BaseModel):
    movie: MovieCard
    score: float
    liked_by: int
    because_of: list[BecauseOf]
    because_taste: BecauseTaste | None = None


class RecommendationsOut(BaseModel):
    strategy: Literal["collaborative", "fallback"]
    session_id: str
    items: list[RecommendationItem]


class RatingIn(BaseModel):
    movie_id: int
    value: StrictInt
    session_id: str | None = None

    @field_validator("value")
    @classmethod
    def _plus_or_minus_one(cls, value: int) -> int:
        if value not in (1, -1):
            raise ValueError("value must be 1 or -1")
        return value


class SeenIn(BaseModel):
    movie_id: int
    type: Literal["not_seen", "watched", "not_interested"]
    session_id: str | None = None


class WriteOut(BaseModel):
    ok: bool
    rated_count: int


class SearchResultOut(BaseModel):
    tmdb_type: Literal["movie", "tv"]
    tmdb_id: int
    title: str
    original_title: str | None
    year: int | None
    poster_path: str | None
    movie_id: int | None
    user_value: int | None


class ResolveIn(BaseModel):
    tmdb_type: Literal["movie", "tv"]
    tmdb_id: PositiveInt


class CategoryPrefIn(BaseModel):
    kind: Literal["collection", "studio", "genre", "anime"]
    key: str = Field(min_length=1, max_length=64)
    show: bool


class CategoryPrefOut(BaseModel):
    """A category the rule hides (``show`` false) or the user chose to show; ``disliked`` of
    ``rated`` is the "N of N"."""

    kind: Literal["collection", "studio", "genre", "anime"]
    key: str
    name: str
    disliked: int
    rated: int
    show: bool
