from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import database
from conftest import REAL_DB_PATH
from models import Course, Event, MeetEntry, Stroke, SwimTime


@pytest.mark.parametrize(
    "stroke, relay, expected",
    [
        (Stroke.IM, False, "200 IM LCM"),
        (Stroke.FR, True, "200 FR-R LCM"),
        (Stroke.IM, True, "200 MED-R LCM"),  # a medley relay is stored as IM + relay
    ],
)
def test_event_name_property(stroke, relay, expected):
    assert Event(distance=200, stroke=stroke, course=Course.LCM, relay=relay).name == expected


def test_foreign_keys_enforced(db):
    db.add(MeetEntry(meet_id=1, swimmer_id=1, event_id=1))
    with pytest.raises(IntegrityError):
        db.commit()


def test_event_unique_constraint(db, swim_event):
    db.add(Event(distance=50, stroke=Stroke.FR, course=Course.SCY))
    with pytest.raises(IntegrityError):
        db.commit()


def test_relay_event_is_distinct_from_individual(db, swim_event):
    db.add(Event(distance=50, stroke=Stroke.FR, course=Course.SCY, relay=True))
    db.commit()  # no IntegrityError: relay is part of the uniqueness key


@pytest.mark.parametrize(
    "fields",
    [
        {"time_seconds": None, "dq": False},  # a result needs a time unless it's a DQ
        {"time_seconds": 30.0, "relay_leg": 5},  # legs are 1-4
    ],
)
def test_swim_time_check_constraints(db, meet_entry, fields):
    db.add(SwimTime(meet_entry_id=meet_entry.id, **fields))
    with pytest.raises(IntegrityError):
        db.commit()


def test_get_db_yields_and_closes_session(monkeypatch):
    closed = []

    class Tracked(Session):
        def close(self):
            closed.append(True)
            super().close()

    monkeypatch.setattr(database, "SessionLocal", lambda: Tracked())
    gen = database.get_db()
    assert isinstance(next(gen), Tracked)
    with pytest.raises(StopIteration):
        next(gen)
    assert closed == [True]


def test_db_path_is_next_to_module():
    assert Path(database.__file__).parent / "swim_tracker.db" == REAL_DB_PATH


def test_tests_never_use_the_real_database():
    """conftest's autouse guard: the app's engine points at a throwaway file during tests."""
    assert database.DB_PATH != REAL_DB_PATH
    assert database.engine.url.database != str(REAL_DB_PATH)
    with database.engine.connect() as conn:
        assert conn.execute(text("select 1")).scalar() == 1
