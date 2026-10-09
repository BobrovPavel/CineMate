"""Pydantic request/response models of the HTTP API."""

from typing import Literal

from pydantic import BaseModel, StrictInt, field_validator


class SessionOut(BaseModel):
    user_id: int


class ProfileItem(BaseModel):
    movie_id: int
    title: str
    year: int | None
    poster_path: str | None
    value: int


class OnboardingCard(BaseModel):
    movie_id: int
    title: str
    year: int | None
    poster_path: str | None
    genres: list[str]


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
