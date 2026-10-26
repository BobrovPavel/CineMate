import shutil
import textwrap

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from cinemate.api.app import create_app
from cinemate.cli import main
from cinemate.db.migrations import (
    DEFAULT_MIGRATIONS_DIR,
    MIGRATIONS_DIR_ENV,
    SchemaNotMigratedError,
    alembic_config,
    current_revision,
    ensure_schema,
    head_revision,
    migrations_dir,
    upgrade_head,
)
from cinemate.db.models import Base
from cinemate.db.session import create_all, make_engine


def _describe(engine):
    """Tables, columns, unique constraints, indexes, FKs and checks of the schema."""
    insp = inspect(engine)
    schema = {}
    for table in sorted(insp.get_table_names()):
        if table == "alembic_version":
            continue
        schema[table] = {
            "columns": {
                c["name"]: (type(c["type"]).__name__, c["nullable"])
                for c in insp.get_columns(table)
            },
            "pk": insp.get_pk_constraint(table)["constrained_columns"],
            "unique": sorted(
                (u["name"] or "", tuple(u["column_names"]))
                for u in insp.get_unique_constraints(table)
            ),
            "indexes": sorted(
                (i["name"], tuple(i["column_names"])) for i in insp.get_indexes(table)
            ),
            "fks": sorted(
                (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
                for f in insp.get_foreign_keys(table)
            ),
            "checks": sorted(
                (c["name"], " ".join(c["sqltext"].split()))
                for c in insp.get_check_constraints(table)
            ),
        }
    return schema


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'm.db'}"


def test_upgrade_head_matches_create_all(tmp_path):
    migrated = make_engine(f"sqlite:///{tmp_path / 'a.db'}")
    created = make_engine(f"sqlite:///{tmp_path / 'b.db'}")
    upgrade_head(migrated)
    create_all(created)
    assert _describe(migrated) == _describe(created)
    assert set(_describe(migrated)) == set(Base.metadata.tables)
    assert current_revision(migrated) == head_revision()


def test_repeated_upgrade_changes_nothing(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'a.db'}")
    upgrade_head(engine)
    before = _describe(engine)
    upgrade_head(engine)
    assert _describe(engine) == before
    assert current_revision(engine) == head_revision()


def test_stamp_existing_marks_head_without_touching_data(db_url, capsys):
    engine = make_engine(db_url)
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO movies (title, genres) VALUES ('Alien', '[]')"))
    before = _describe(engine)
    assert current_revision(engine) is None

    assert main(["migrate", "--database-url", db_url, "--stamp-existing"]) == 0
    assert current_revision(engine) == head_revision()
    assert _describe(engine) == before
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title FROM movies")).scalars().all() == ["Alien"]
    # Normal migrations work afterwards.
    assert main(["migrate", "--database-url", db_url]) == 0


def test_migrate_command_on_empty_database(db_url, capsys):
    assert main(["migrate", "--database-url", db_url]) == 0
    assert current_revision(make_engine(db_url)) == head_revision()
    assert "up to date" in capsys.readouterr().out


def test_migrate_refuses_legacy_database_without_stamp(db_url, capsys):
    create_all(make_engine(db_url))
    assert main(["migrate", "--database-url", db_url]) == 2
    assert "--stamp-existing" in capsys.readouterr().err


def test_stamp_existing_errors(db_url, capsys):
    assert main(["migrate", "--database-url", db_url, "--stamp-existing"]) == 2
    assert "no tables" in capsys.readouterr().err
    assert main(["migrate", "--database-url", db_url]) == 0
    assert main(["migrate", "--database-url", db_url, "--stamp-existing"]) == 2
    assert "already under migration control" in capsys.readouterr().err


def test_migrate_uses_database_url_env(monkeypatch, db_url):
    monkeypatch.setenv("DATABASE_URL", db_url)
    assert main(["migrate"]) == 0
    assert current_revision(make_engine(db_url)) == head_revision()


def test_migration_adding_nullable_column_keeps_rows(tmp_path, db_url):
    scripts = tmp_path / "migrations"
    shutil.copytree(DEFAULT_MIGRATIONS_DIR, scripts, ignore=shutil.ignore_patterns("__pycache__"))
    (scripts / "versions" / "0005_add_note.py").write_text(
        textwrap.dedent(
            """
            import sqlalchemy as sa
            from alembic import op

            revision = "0005"
            down_revision = "0004"
            branch_labels = None
            depends_on = None


            def upgrade():
                op.add_column("movies", sa.Column("note", sa.String(32), nullable=True))


            def downgrade():
                op.drop_column("movies", "note")
            """
        )
    )
    engine = make_engine(db_url)
    upgrade_head(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO movies (title, genres) VALUES ('Alien', '[]')"))
    upgrade_head(engine, scripts)
    assert current_revision(engine) == head_revision(scripts) == "0005"
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT title, note FROM movies")).all()
    assert [tuple(r) for r in rows] == [("Alien", None)]


def test_migration_0002_adds_external_ratings_id_to_existing_database(db_url):
    engine = make_engine(db_url)
    command.upgrade(alembic_config(engine), "0001")
    assert current_revision(engine) == "0001"
    assert "external_ratings_id" not in {c["name"] for c in inspect(engine).get_columns("movies")}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO movies (title, genres) VALUES ('Alien', '[]')"))
    assert main(["migrate", "--database-url", db_url]) == 0
    assert current_revision(engine) == head_revision()
    insp = inspect(engine)
    for table in ("movies", "users"):
        assert "external_ratings_id" in {c["name"] for c in insp.get_columns(table)}
        assert ("external_ratings_id",) in {
            tuple(u["column_names"]) for u in insp.get_unique_constraints(table)
        }
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title FROM movies")).scalars().all() == ["Alien"]


def test_create_app_in_memory_works_as_before():
    app = create_app("sqlite:///:memory:")
    assert set(inspect(app.state.engine).get_table_names()) >= set(Base.metadata.tables)


def test_create_app_initialises_empty_sqlite_file(db_url):
    app = create_app(db_url)
    assert current_revision(app.state.engine) == head_revision()


def test_create_app_rejects_unmigrated_file_database(db_url):
    create_all(make_engine(db_url))
    with pytest.raises(SchemaNotMigratedError, match="--stamp-existing"):
        create_app(db_url)


def test_create_app_rejects_outdated_database(db_url):
    engine = make_engine(db_url)
    upgrade_head(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '0000'"))
    with pytest.raises(SchemaNotMigratedError, match="cinemate migrate"):
        ensure_schema(engine)


def test_create_app_accepts_migrated_database(db_url):
    upgrade_head(make_engine(db_url))
    assert create_app(db_url).state.engine is not None


def test_serve_reports_unmigrated_database(db_url, capsys, monkeypatch):
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: pytest.fail("must not start"))
    create_all(make_engine(db_url))
    assert main(["serve", "--database-url", db_url]) == 2
    assert "cinemate migrate" in capsys.readouterr().err


def test_migrations_dir_can_be_overridden_by_env(monkeypatch, tmp_path):
    copy = tmp_path / "elsewhere"
    shutil.copytree(DEFAULT_MIGRATIONS_DIR, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setenv(MIGRATIONS_DIR_ENV, str(copy))
    assert migrations_dir() == copy
    engine = make_engine(f"sqlite:///{tmp_path / 'e.db'}")
    upgrade_head(engine)
    assert current_revision(engine) == head_revision()


def test_migrations_dir_defaults_to_checkout(monkeypatch):
    monkeypatch.delenv(MIGRATIONS_DIR_ENV, raising=False)
    assert migrations_dir() == DEFAULT_MIGRATIONS_DIR
    assert (DEFAULT_MIGRATIONS_DIR / "env.py").is_file()


def test_head_revision_without_scripts_fails_clearly(tmp_path):
    empty = tmp_path / "empty"
    (empty / "versions").mkdir(parents=True)
    with pytest.raises(RuntimeError, match=MIGRATIONS_DIR_ENV):
        head_revision(empty)


def test_migration_0003_adds_title_ru_to_existing_database(db_url):
    engine = make_engine(db_url)
    command.upgrade(alembic_config(engine), "0002")
    assert "title_ru" not in {c["name"] for c in inspect(engine).get_columns("movies")}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO movies (title, genres) VALUES ('Alien', '[]')"))
    assert main(["migrate", "--database-url", db_url]) == 0
    assert current_revision(engine) == head_revision()
    assert "title_ru" in {c["name"] for c in inspect(engine).get_columns("movies")}
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT title, title_ru FROM movies")).all()
    assert [tuple(r) for r in rows] == [("Alien", None)]


def _insert_movie(conn, movie_id, title="Heat", **cols):
    cols = {"id": movie_id, "title": title, "genres": "[]", **cols}
    names = ", ".join(cols)
    marks = ", ".join(f":{k}" for k in cols)
    conn.execute(text(f"INSERT INTO movies ({names}) VALUES ({marks})"), cols)


def test_migration_0004_moves_ids_merges_duplicates_and_keeps_ratings(db_url):
    engine = make_engine(db_url)
    command.upgrade(alembic_config(engine), "0003")
    with engine.begin() as conn:
        _insert_movie(conn, 1, external_movielens_id=10, imdb_id="tt0113277", tmdb_id=949)
        _insert_movie(conn, 2, external_movielens_id=20, imdb_id="tt0113277", tmdb_id=949)
        _insert_movie(conn, 3, external_ratings_id=7, external_kinopoisk_id=99)
        for uid in (1, 2, 3):
            conn.execute(
                text("INSERT INTO users (id, is_synthetic, created_at) VALUES (:i, 1, :t)"),
                {"i": uid, "t": "2024-01-01 00:00:00"},
            )
        ins = "INSERT INTO ratings (user_id, movie_id, value, created_at) VALUES (:u, :m, :v, :t)"
        for u, m, v, t in [
            (1, 1, 1, "2024-01-01 00:00:00"),  # both rated: the later one (movie 2) wins
            (1, 2, -1, "2024-02-01 00:00:00"),
            (2, 1, -1, "2024-03-01 00:00:00"),  # both rated: the later one (movie 1) wins
            (2, 2, 1, "2024-01-01 00:00:00"),
            (3, 2, 1, "2024-01-01 00:00:00"),  # only on the dropped movie: moved
        ]:
            conn.execute(text(ins), {"u": u, "m": m, "v": v, "t": t})
        conn.execute(
            text(
                "INSERT INTO seen_marks (user_id, movie_id, type) VALUES "
                "(1, 1, 'watched'), (1, 2, 'not_interested'), (2, 2, 'watched')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO events (user_id, session_id, type, movie_id, created_at) "
                "VALUES (1, 's', 'like', 2, '2024-01-01 00:00:00')"
            )
        )

    assert main(["migrate", "--database-url", db_url]) == 0

    with engine.connect() as conn:
        movies = conn.execute(text("SELECT id, tmdb_type, tmdb_id FROM movies ORDER BY id")).all()
        assert [tuple(r) for r in movies] == [(1, "movie", 949), (3, None, None)]
        ext = conn.execute(
            text("SELECT source, external_id, movie_id FROM movie_external_ids ORDER BY 1, 2")
        ).all()
        assert [tuple(r) for r in ext] == [
            ("imdb", "tt0113277", 1),
            ("kinopoisk", "99", 3),
            ("movielens", "10", 1),
            ("movielens", "20", 1),
            ("ratings_csv", "7", 3),
        ]
        ratings = conn.execute(
            text("SELECT user_id, movie_id, value FROM ratings ORDER BY user_id")
        ).all()
        assert [tuple(r) for r in ratings] == [(1, 1, -1), (2, 1, -1), (3, 1, 1)]
        marks = conn.execute(
            text("SELECT user_id, movie_id, type FROM seen_marks ORDER BY user_id")
        ).all()
        assert [tuple(r) for r in marks] == [(1, 1, "not_interested"), (2, 1, "watched")]
        assert conn.execute(text("SELECT movie_id FROM events")).scalars().all() == [1]


def test_tmdb_pair_is_unique_but_null_is_allowed(db_url):
    engine = make_engine(db_url)
    upgrade_head(engine)
    with engine.begin() as conn:
        _insert_movie(conn, 1, tmdb_type="movie", tmdb_id=1)
        _insert_movie(conn, 2, tmdb_type="tv", tmdb_id=1)
        _insert_movie(conn, 3)
        _insert_movie(conn, 4)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _insert_movie(conn, 5, tmdb_type="movie", tmdb_id=1)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _insert_movie(conn, 6, tmdb_type="book", tmdb_id=2)
