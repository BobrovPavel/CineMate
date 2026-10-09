"""Session and profile endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from cinemate.api.deps import (
    SESSION_COOKIE,
    get_current_user,
    get_db_session,
    get_matrix_store,
    session_token,
)
from cinemate.api.schemas import (
    BecauseOf,
    MovieCard,
    OnboardingCard,
    ProfileItem,
    RatingIn,
    RecommendationItem,
    RecommendationsOut,
    SeenIn,
    SessionOut,
    WriteOut,
)
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, User
from cinemate.services.events import log_impressions, log_reaction
from cinemate.services.onboarding import onboarding_for_user
from cinemate.services.recommendations import get_recommendations
from cinemate.services.users import (
    create_session_user,
    get_ratings,
    get_user_by_token,
    set_rating,
    set_seen_mark,
)

COOKIE_MAX_AGE = 365 * 24 * 3600

router = APIRouter(prefix="/api")


@router.post("/session", response_model=SessionOut)
def open_session(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> SessionOut:
    """Create an anonymous user and set the session cookie, or reuse the one in the cookie."""
    token = session_token(request)
    user = get_user_by_token(session, token) if token else None
    if user is None:
        user = create_session_user(session)
        response.set_cookie(
            SESSION_COOKIE,
            user.session_token or "",
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.app.state.cookie_secure,
        )
    return SessionOut(user_id=user.id)


@router.get("/profile", response_model=list[ProfileItem])
def profile(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ProfileItem]:
    """Ratings of the current user, newest first."""
    items = []
    for rating in reversed(get_ratings(session, user)):
        movie = session.get(Movie, rating.movie_id)
        if movie is None:
            continue
        items.append(
            ProfileItem(
                movie_id=movie.id,
                title=movie.title,
                year=movie.year,
                poster_path=movie.poster_path,
                value=rating.value,
            )
        )
    return items


@router.get("/onboarding", response_model=list[OnboardingCard])
def onboarding(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    store: Annotated[MatrixStore, Depends(get_matrix_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[OnboardingCard]:
    """Cards to rate during onboarding; already rated or marked movies are excluded."""
    return [
        OnboardingCard(
            movie_id=movie.id,
            title=movie.title,
            year=movie.year,
            poster_path=movie.poster_path,
            genres=list(movie.genres or []),
        )
        for movie in onboarding_for_user(session, store, user, n=limit)
    ]


@router.post("/ratings", response_model=WriteOut)
def rate(
    body: RatingIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    store: Annotated[MatrixStore, Depends(get_matrix_store)],
) -> WriteOut:
    """Set the user's rating; log a reaction event when ``session_id`` is given."""
    try:
        set_rating(session, user, body.movie_id, body.value, store)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="movie not found") from exc
    if body.session_id:
        log_reaction(
            session, user, body.session_id, body.movie_id, "like" if body.value == 1 else "dislike"
        )
    return WriteOut(ok=True, rated_count=len(get_ratings(session, user)))


@router.post("/seen", response_model=WriteOut)
def seen(
    body: SeenIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> WriteOut:
    """Set a seen mark; ``watched``/``not_interested`` are logged when ``session_id`` is given."""
    try:
        set_seen_mark(session, user, body.movie_id, body.type)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="movie not found") from exc
    if body.session_id and body.type != "not_seen":
        log_reaction(session, user, body.session_id, body.movie_id, body.type)
    return WriteOut(ok=True, rated_count=len(get_ratings(session, user)))


def _card(movie: Movie) -> MovieCard:
    return MovieCard(
        id=movie.id,
        title=movie.title,
        original_title=movie.original_title,
        year=movie.year,
        overview=movie.overview,
        poster_path=movie.poster_path,
        genres=list(movie.genres or []),
        runtime=movie.runtime,
    )


@router.get("/recommendations", response_model=RecommendationsOut)
def recommendations(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    store: Annotated[MatrixStore, Depends(get_matrix_store)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> RecommendationsOut:
    """Recommendations with explanations; each call is a new session with logged impressions."""
    result = get_recommendations(session, store, user, limit=limit)
    session_id = uuid.uuid4().hex
    log_impressions(session, user, session_id, [i.movie.id for i in result.items], result.strategy)
    return RecommendationsOut(
        strategy=result.strategy,
        session_id=session_id,
        items=[
            RecommendationItem(
                movie=_card(item.movie),
                score=item.score,
                liked_by=item.liked_by,
                because_of=[BecauseOf(movie_id=m.id, title=m.title) for m in item.because_of],
            )
            for item in result.items
        ],
    )


@router.get("/movies/{movie_id}", response_model=MovieCard)
def movie_detail(
    movie_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MovieCard:
    """Full movie card; ``404`` for an unknown id."""
    movie = session.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="movie not found")
    return _card(movie)
