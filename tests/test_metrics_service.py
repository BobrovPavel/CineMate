from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from cinemate.cli import main
from cinemate.db.models import Event, Movie, User
from cinemate.db.session import create_all, make_engine
from cinemate.services.metrics import (
    good_session_rate,
    good_session_rate_by_strategy,
    metrics_by_variant,
    retention_7d,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with sessionmaker(engine)() as s:
        s.add(Movie(id=1, title="a"))
        s.add_all([User(), User()])
        s.flush()
        yield s


def ev(session, sid, type_, strategy=None, user_id=1, at=T0, variant=None):
    session.add(
        Event(
            user_id=user_id,
            session_id=sid,
            type=type_,
            movie_id=1,
            strategy=strategy,
            variant=variant,
            created_at=at,
        )
    )
    session.flush()


def test_empty_db(session):
    assert good_session_rate(session).rate == 0.0
    assert good_session_rate(session).total == 0
    assert good_session_rate_by_strategy(session) == {}
    assert retention_7d(session) == 0.0


def test_good_session_rate(session):
    ev(session, "a", "impression", "collaborative")
    ev(session, "a", "like")
    ev(session, "a", "like")
    ev(session, "b", "impression", "collaborative")
    ev(session, "b", "dislike")
    ev(session, "c", "impression", "fallback")
    r = good_session_rate(session)
    assert (r.total, r.good) == (3, 1)
    assert r.rate == pytest.approx(1 / 3)


def test_like_without_impression_is_not_a_session(session):
    ev(session, "x", "like")
    assert good_session_rate(session).total == 0


def test_since_filter(session):
    ev(session, "old", "impression", "fallback", at=T0)
    ev(session, "old", "like", at=T0)
    ev(session, "new", "impression", "fallback", at=T0 + timedelta(days=10))
    r = good_session_rate(session, since=T0 + timedelta(days=5))
    assert (r.total, r.good) == (1, 0)


def test_by_strategy(session):
    ev(session, "a", "impression", "collaborative")
    ev(session, "a", "like")
    ev(session, "b", "impression", "fallback")
    ev(session, "c", "impression", None)
    by = good_session_rate_by_strategy(session)
    assert set(by) == {"collaborative", "fallback", "unknown"}
    assert by["collaborative"].rate == 1.0
    assert by["fallback"].rate == 0.0


def test_retention_7d(session):
    now = T0 + timedelta(days=30)
    # user 1 returns on day 3 -> retained; user 2 never returns -> not retained
    ev(session, "a", "impression", "fallback", user_id=1, at=T0)
    ev(session, "b", "impression", "fallback", user_id=1, at=T0 + timedelta(days=3))
    ev(session, "c", "impression", "fallback", user_id=2, at=T0)
    ev(session, "d", "impression", "fallback", user_id=2, at=T0 + timedelta(days=20))
    assert retention_7d(session, now=now) == 0.5


def test_retention_ignores_recent_users(session):
    ev(session, "a", "impression", "fallback", user_id=1, at=T0)
    assert retention_7d(session, now=T0 + timedelta(days=3)) == 0.0


def test_cli_metrics(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    assert main(["metrics", "--database-url", url]) == 0
    out = capsys.readouterr().out
    assert "good session rate: 0.0000 (0/0 sessions)" in out
    assert "7-day retention: 0.0000" in out


def test_cli_metrics_invalid_since():
    with pytest.raises(SystemExit):
        main(["metrics", "--since", "nonsense"])


def test_since_drops_session_whose_impression_is_before_since(session):
    ev(session, "a", "impression", "fallback", at=T0)
    ev(session, "a", "like", at=T0 + timedelta(days=10))
    assert good_session_rate(session, since=T0 + timedelta(days=5)).total == 0


def test_retention_boundary_exactly_7_days(session):
    ev(session, "a", "impression", "fallback", user_id=1, at=T0)
    ev(session, "b", "impression", "fallback", user_id=1, at=T0 + timedelta(days=7))
    ev(session, "c", "impression", "fallback", user_id=2, at=T0)
    ev(session, "d", "impression", "fallback", user_id=2, at=T0 + timedelta(days=7, seconds=1))
    assert retention_7d(session, now=T0 + timedelta(days=30)) == 0.5


def test_retention_naive_now_and_single_old_event(session):
    ev(session, "a", "impression", "fallback", user_id=1, at=T0)
    assert retention_7d(session, now=datetime(2026, 2, 1)) == 0.0


def test_cli_metrics_with_data_and_since(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    engine = make_engine(url)
    create_all(engine)
    with sessionmaker(engine)() as s:
        s.add_all([Movie(id=1, title="a"), User()])
        s.flush()
        ev(s, "a", "impression", "collaborative")
        ev(s, "a", "like")
        s.commit()
    assert main(["metrics", "--database-url", url]) == 0
    out = capsys.readouterr().out
    assert "good session rate: 1.0000 (1/1 sessions)" in out
    assert "  collaborative: 1.0000 (1/1)" in out
    assert main(["metrics", "--database-url", url, "--since", "2030-01-01"]) == 0
    assert "(0/0 sessions)" in capsys.readouterr().out


def test_cli_metrics_invalid_since_message(capsys):
    with pytest.raises(SystemExit):
        main(["metrics", "--since", "nonsense"])
    assert "invalid ISO date/time" in capsys.readouterr().err


def _variant_log(session):
    # user 1 -> control, user 2 -> taste
    ev(session, "a", "impression", "collaborative", 1, variant="control")
    ev(session, "a", "like", user_id=1, variant="control")
    ev(session, "a", "dislike", user_id=1, variant="control")
    ev(session, "a", "not_interested", user_id=1, variant="control")
    ev(session, "b", "impression", "collaborative", 1, variant="control")
    ev(session, "c", "impression", "collaborative", 2, variant="taste")
    ev(session, "c", "like", user_id=2, variant="taste")
    ev(session, "c", "like", user_id=2, variant="taste")
    ev(session, "d", "impression", "fallback", 2)
    ev(session, "stray", "like", user_id=2)


def test_metrics_by_variant(session):
    _variant_log(session)
    result = metrics_by_variant(session, now=T0 + timedelta(days=1))
    assert list(result) == ["control", "none", "taste"]
    control = result["control"]
    assert (control.users, control.sessions, control.good_sessions) == (1, 2, 1)
    assert control.good_session_rate == pytest.approx(0.5)
    assert (control.likes, control.dislikes, control.like_dislike_ratio) == (1, 1, 1.0)
    assert control.not_interested_share == pytest.approx(1 / 3)
    taste = result["taste"]
    assert (taste.users, taste.sessions, taste.good_session_rate) == (1, 1, 1.0)
    assert (taste.likes, taste.dislikes, taste.like_dislike_ratio) == (2, 0, None)
    assert taste.not_interested_share == 0.0
    none = result["none"]
    assert (none.users, none.sessions, none.good_session_rate) == (1, 1, 0.0)


def test_metrics_by_variant_retention_and_since(session):
    ev(session, "a", "impression", None, 1, variant="control")
    ev(session, "a", "like", user_id=1, at=T0 + timedelta(days=3), variant="control")
    ev(session, "b", "impression", None, 2, at=T0, variant="taste")
    now = T0 + timedelta(days=10)
    result = metrics_by_variant(session, now=now)
    assert result["control"].retention_7d == 1.0
    assert result["taste"].retention_7d == 0.0
    later = metrics_by_variant(session, since=T0 + timedelta(days=1), now=now)
    assert later == {}


def test_metrics_by_variant_empty(session):
    assert metrics_by_variant(session) == {}


def test_cli_metrics_by_variant(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'v.db'}"
    engine = make_engine(url)
    create_all(engine)
    with sessionmaker(engine)() as s:
        s.add(Movie(id=1, title="a"))
        s.add_all([User(), User()])
        s.flush()
        _variant_log(s)
        s.commit()
    assert main(["metrics", "--database-url", url]) == 0
    assert "by variant" not in capsys.readouterr().out
    assert main(["metrics", "--database-url", url, "--by-variant"]) == 0
    out = capsys.readouterr().out
    assert "control: users 1, sessions 2" in out
    assert "likes/dislikes 1.00 (1/1)" in out
    assert "likes/dislikes n/a (2/0)" in out
