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
    get_tmdb_client,
    language_from_request,
    session_token,
)
from cinemate.api.schemas import (
    BecauseOf,
    BecauseTaste,
    CategoryPrefIn,
    CategoryPrefOut,
    MeOut,
    MovieCard,
    OnboardingCard,
    ProfileItem,
    RatingIn,
    RecommendationItem,
    RecommendationsOut,
    ResolveIn,
    SearchResultOut,
    SeenIn,
    SessionOut,
    WriteOut,
)
from cinemate.db.catalog import import_from_tmdb
from cinemate.db.details import ensure_extended
from cinemate.db.features import genre_names_by_movie
from cinemate.db.matrix_store import MatrixStore
from cinemate.db.models import Movie, User
from cinemate.services.ab import assign_variant, settings_for_variant
from cinemate.services.categories import get_category_prefs, set_category_pref
from cinemate.services.events import log_impressions, log_reaction
from cinemate.services.onboarding import onboarding_for_user
from cinemate.services.recommendations import get_recommendations
from cinemate.services.search import search_local, search_movies
from cinemate.services.users import (
    create_session_user,
    get_ratings,
    get_user_by_token,
    pool_for_language,
    set_rating,
    set_seen_mark,
    tmdb_language_for,
)
from cinemate.tmdb import TmdbClient, TmdbError, certification_country_for

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
        user = _new_session_user(request, response, session)
    return SessionOut(user_id=user.id, pool=user.pool)


def _new_session_user(request: Request, response: Response, session: Session) -> User:
    """Create an anonymous user in the pool of the request language and set its cookie."""
    user = create_session_user(session, pool_for_language(language_from_request(request)))
    response.set_cookie(
        SESSION_COOKIE,
        user.session_token or "",
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.app.state.cookie_secure,
    )
    return user


@router.post("/session/reset", response_model=SessionOut)
def reset_session(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db_session)],
) -> SessionOut:
    """Start over: a new anonymous user (pool by language); the old user stays in the DB."""
    user = _new_session_user(request, response, session)
    return SessionOut(user_id=user.id, pool=user.pool)


@router.get("/me", response_model=MeOut)
def me(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MeOut:
    """The current user's id, pool and number of ratings."""
    return MeOut(user_id=user.id, pool=user.pool, rated_count=len(get_ratings(session, user)))


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
                title_ru=movie.title_ru,
                year=movie.year,
                poster_path=movie.poster_path,
                value=rating.value,
            )
        )
    return items


@router.get("/onboarding", response_model=list[OnboardingCard])
def onboarding(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    store: Annotated[MatrixStore, Depends(get_matrix_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[OnboardingCard]:
    """Cards to rate during onboarding; already rated or marked movies are excluded."""
    movies = onboarding_for_user(session, store, user, n=limit)
    genres = _genre_names(session, request, [m.id for m in movies])
    return [
        OnboardingCard(
            movie_id=movie.id,
            title=movie.title,
            title_ru=movie.title_ru,
            year=movie.year,
            poster_path=movie.poster_path,
            genres=genres.get(movie.id, []),
        )
        for movie in movies
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


def _genre_names(session: Session, request: Request, movie_ids: list[int]) -> dict[int, list[str]]:
    """Genre names of the movies in the language of the request."""
    return genre_names_by_movie(session, movie_ids, language_from_request(request))


def _card(movie: Movie, genres: list[str]) -> MovieCard:
    return MovieCard(
        id=movie.id,
        title=movie.title,
        title_ru=movie.title_ru,
        original_title=movie.original_title,
        year=movie.year,
        overview=movie.overview,
        poster_path=movie.poster_path,
        genres=genres,
        runtime=movie.runtime,
    )


@router.get("/recommendations", response_model=RecommendationsOut)
def recommendations(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    store: Annotated[MatrixStore, Depends(get_matrix_store)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> RecommendationsOut:
    """Recommendations with explanations; each call is a new session with logged impressions."""
    settings = request.app.state.recommender_settings
    variant = assign_variant(settings, user.id)
    result = get_recommendations(
        session,
        store,
        user,
        limit=limit,
        settings=settings_for_variant(settings, variant),
        language=language_from_request(request),
    )
    session_id = uuid.uuid4().hex
    genres = _genre_names(session, request, [i.movie.id for i in result.items])
    log_impressions(
        session, user, session_id, [i.movie.id for i in result.items], result.strategy, variant
    )
    return RecommendationsOut(
        strategy=result.strategy,
        session_id=session_id,
        items=[
            RecommendationItem(
                movie=_card(item.movie, genres.get(item.movie.id, [])),
                score=item.score,
                liked_by=item.liked_by,
                because_of=[
                    BecauseOf(movie_id=m.id, title=m.title, title_ru=m.title_ru)
                    for m in item.because_of
                ],
                because_taste=(
                    BecauseTaste(
                        kind=item.because_taste.kind,
                        id=item.because_taste.id,
                        name=item.because_taste.name,
                    )
                    if item.because_taste
                    else None
                ),
            )
            for item in result.items
        ],
    )


@router.get("/category-prefs", response_model=list[CategoryPrefOut])
def category_prefs(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    store: Annotated[MatrixStore, Depends(get_matrix_store)],
) -> list[CategoryPrefOut]:
    """Categories lowered in the feed by the rule and those the user chose to show."""
    views = get_category_prefs(
        session,
        store,
        user,
        settings=request.app.state.recommender_settings,
        language=language_from_request(request),
    )
    return [CategoryPrefOut(**vars(view)) for view in views]


@router.post("/category-prefs", response_model=WriteOut)
def set_category_pref_route(
    body: CategoryPrefIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> WriteOut:
    """``show: true`` keeps the category in the feed, ``false`` restores the automatic rule."""
    set_category_pref(session, user, body.kind, body.key, body.show)
    return WriteOut(ok=True, rated_count=len(get_ratings(session, user)))


@router.get("/search", response_model=list[SearchResultOut])
def search(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    q: Annotated[str, Query(min_length=2, max_length=100)],
    page: Annotated[int, Query(ge=1, le=100)] = 1,
) -> list[SearchResultOut]:
    """Search movies and TV shows in our catalog or TMDB (``SEARCH_SOURCE``).

    The language follows the ``cinemate_lang`` cookie, then ``Accept-Language``.
    """
    if len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="q must have at least 2 characters")
    language = tmdb_language_for(language_from_request(request))
    selector = request.app.state.search_selector
    client: TmdbClient | None = request.app.state.tmdb_client
    use_local = selector.mode == "local" or (selector.mode == "auto" and selector.catalog_ready())
    if selector.mode == "auto" and client is None:
        use_local = True  # no key: our own catalog is the only source
    try:
        if use_local:
            results = search_local(session, q, page, language=language, user=user)
            if not results and page == 1 and selector.mode == "auto" and client is not None:
                try:
                    results = search_movies(
                        session, client, request.app.state.search_cache, user, q, language, page
                    )
                except TmdbError:
                    results = []  # the fallback is best effort
        else:
            if client is None:
                raise HTTPException(
                    status_code=503, detail="поиск недоступен: не задан TMDB_API_KEY"
                )
            results = search_movies(
                session, client, request.app.state.search_cache, user, q, language, page
            )
    except TmdbError as exc:
        raise HTTPException(status_code=502, detail="ошибка TMDB") from exc
    return [
        SearchResultOut(
            tmdb_type=r.item.tmdb_type,
            tmdb_id=r.item.tmdb_id,
            title=r.item.title,
            original_title=r.item.original_title,
            year=r.item.year,
            poster_path=r.item.poster_path,
            movie_id=r.movie_id,
            user_value=r.user_value,
        )
        for r in results
    ]


@router.post("/movies/resolve", response_model=MovieCard)
def resolve_movie(
    request: Request,
    body: ResolveIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    client: Annotated[TmdbClient, Depends(get_tmdb_client)],
) -> MovieCard:
    """Our card for a TMDB movie or show, creating it in the catalog on first use."""
    try:
        movie = import_from_tmdb(session, client, body.tmdb_type, body.tmdb_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="movie not found") from exc
    except TmdbError as exc:
        raise HTTPException(status_code=502, detail="ошибка TMDB") from exc
    return _card(movie, _genre_names(session, request, [movie.id]).get(movie.id, []))


@router.get("/movies/{movie_id}", response_model=MovieCard)
def movie_detail(
    request: Request,
    movie_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> MovieCard:
    """Full movie card; ``404`` for an unknown id."""
    movie = session.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="movie not found")
    ensure_extended(
        session,
        request.app.state.tmdb_client,
        movie,
        certification_country_for(language_from_request(request)),
    )
    return _card(movie, _genre_names(session, request, [movie.id]).get(movie.id, []))
