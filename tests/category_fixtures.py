"""Seed data for the hidden-categories tests.

User 1 is the target: likes movies 1..6 and dislikes the first ``dislikes`` of movies 30..34
(a franchise / studio / genre of "Marvel" movies). Users 2..8 like everything of 1..6 and 30..34.
Candidates: movies 40..42 of the same category liked by all 7 neighbours, and 20 other drama
movies 50..69 liked by 3 of them, so without the rule the category candidates come first.
"""

from cinemate.db.models import Collection, Company, Movie, MovieCompany, MovieGenre, Rating, User

ACTION, DRAMA = 28, 18
MARVEL = [30, 31, 32, 33, 34]
MARVEL_CANDIDATES = [40, 41, 42]
OTHER = list(range(50, 70))
CF = dict(k=150, lam=1.0, min_overlap=1, pop_penalty=0.0, min_user_ratings=2, taste_weight=0.0)


def seed(session, dislikes=5, company=True, collection=False, target_likes=()):
    category = MARVEL + MARVEL_CANDIDATES
    ids = [*range(1, 7), *category, *OTHER]
    session.add_all([Movie(id=i, title=f"m{i}", tmdb_type="movie") for i in ids])
    session.add_all([User(id=i) for i in range(1, 9)])
    if company:
        session.add(Company(id=1, name="Marvel Studios"))
    if collection:
        session.add(Collection(id=1, name="Avengers Collection"))
    session.flush()
    for m in category:
        session.add(MovieGenre(movie_id=m, genre_id=ACTION))
        if company:
            session.add(MovieCompany(movie_id=m, company_id=1))
        if collection:
            session.get(Movie, m).collection_id = 1
    for m in [*range(1, 7), *OTHER]:
        session.add(MovieGenre(movie_id=m, genre_id=DRAMA))
    for u in range(1, 9):
        for m in range(1, 7):
            session.add(Rating(user_id=u, movie_id=m, value=1))
    for u in range(2, 9):
        for m in MARVEL + MARVEL_CANDIDATES:
            session.add(Rating(user_id=u, movie_id=m, value=1))
        if u <= 4:
            for m in OTHER:
                session.add(Rating(user_id=u, movie_id=m, value=1))
    for m in MARVEL[:dislikes]:
        session.add(Rating(user_id=1, movie_id=m, value=-1))
    for m in target_likes:
        session.add(Rating(user_id=1, movie_id=m, value=1))
    session.flush()
