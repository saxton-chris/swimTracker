import runpy

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import database
from models import Course, Event, MeetEntry, Stroke


def test_event_name_property():
    assert Event(distance=200, stroke=Stroke.IM, course=Course.LCM).name == "200 IM LCM"


def test_foreign_keys_enforced(db):
    db.add(MeetEntry(meet_id=1, swimmer_id=1, event_id=1))
    with pytest.raises(IntegrityError):
        db.commit()


def test_event_unique_constraint(db, swim_event):
    db.add(Event(distance=50, stroke=Stroke.FR, course=Course.SCY))
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
    assert database.DB_PATH.parent.name == "app"


def test_create_db_script(monkeypatch, capsys):
    from sqlalchemy import create_engine

    eng = create_engine("sqlite://")
    monkeypatch.setattr(database, "engine", eng)
    runpy.run_module("create_db", run_name="__main__")
    assert {"swimmers", "meets", "events", "meet_entries", "swim_times", "time_standards"} <= set(
        inspect(eng).get_table_names()
    )
    assert "Database created successfully." in capsys.readouterr().out
    eng.dispose()
