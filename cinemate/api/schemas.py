"""Pydantic request/response models of the HTTP API."""

from pydantic import BaseModel


class SessionOut(BaseModel):
    user_id: int


class ProfileItem(BaseModel):
    movie_id: int
    title: str
    year: int | None
    poster_path: str | None
    value: int
