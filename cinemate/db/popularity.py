"""Movie popularity: the number of ``+1`` ratings."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from cinemate.db.models import Movie, Rating


def update_popularity(session: Session, batch_size: int = 1000) -> int:
    """Set ``Movie.popularity_score`` to the like count; return how many values changed."""
    likes = dict(
        session.execute(
            select(Rating.movie_id, func.count()).where(Rating.value == 1).group_by(Rating.movie_id)
        ).all()
    )
    current = session.execute(select(Movie.id, Movie.popularity_score)).all()
    changes = [
        {"id": movie_id, "popularity_score": float(likes.get(movie_id, 0))}
        for movie_id, score in current
        if score != likes.get(movie_id, 0)
    ]
    for start in range(0, len(changes), batch_size):
        session.execute(update(Movie), changes[start : start + batch_size])
    return len(changes)
