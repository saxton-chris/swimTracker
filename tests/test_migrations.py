"""Alembic migrations (app/migrations) and create_db.py, on throwaway SQLite files."""

import runpy
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

import database
from models import Base

APP = Path(database.__file__).parent


def alembic_config(path):
    config = Config(APP / "alembic.ini")
    config.attributes["url"] = f"sqlite:///{path}"
    return config


def revision(path):
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        rev = MigrationContext.configure(conn).get_current_revision()
    engine.dispose()
    return rev


def head():
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(APP / "alembic.ini")).get_current_head()


def test_migrations_build_exactly_the_models_schema(tmp_path):
    """If this fails, models.py changed without a migration: run `alembic revision --autogenerate`."""
    path = tmp_path / "m.db"
    command.upgrade(alembic_config(path), "head")
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diffs == []


def run_create_db(capsys):
    runpy.run_module("create_db", run_name="__main__")
    return capsys.readouterr().out


def test_create_db_makes_a_fresh_database(capsys):
    # conftest points database.engine / DB_PATH at a throwaway file
    out = run_create_db(capsys)
    assert "Database is up to date" in out
    assert "without migration history" not in out
    assert revision(database.DB_PATH) == head()
    con = sqlite3.connect(database.DB_PATH)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}
    con.close()
    assert {"swimmers", "meets", "events", "meet_entries", "swim_times", "time_standards"} <= tables


@pytest.mark.parametrize("empty_version_table", [False, True])
def test_create_db_upgrades_a_pre_alembic_database(capsys, empty_version_table):
    """A database made before Alembic (the 0001 schema, no recorded revision) keeps its rows."""
    path = database.DB_PATH
    command.upgrade(alembic_config(path), "0001")
    con = sqlite3.connect(path)
    con.executescript(
        """
        insert into swimmers (id, name, birthdate, gender) values (1, 'Alistair Saxton', '2016-01-01', 'M');
        insert into meets (id, name, date) values (1, 'State', '2026-07-25');
        insert into events (id, distance, stroke, course) values (1, 50, 'FR', 'LCM');
        insert into meet_entries (id, meet_id, swimmer_id, event_id) values (1, 1, 1, 1);
        insert into swim_times (id, meet_entry_id, time_seconds, notes) values (1, 1, 36.16, 'place 25');
        """
    )
    # Pre-Alembic: no revision recorded (either no table at all, or an empty one).
    con.execute("delete from alembic_version" if empty_version_table else "drop table alembic_version")
    con.commit()
    con.close()

    out = run_create_db(capsys)
    assert "marking it as revision 0001" in out
    assert revision(path) == head()

    con = sqlite3.connect(path)
    assert con.execute("select time_seconds, notes, dq, dq_reason, relay_leg from swim_times").fetchall() == [
        (36.16, "place 25", 0, None, None)
    ]
    assert con.execute("select distance, stroke, course, relay from events").fetchall() == [(50, "FR", "LCM", 0)]
    con.close()

    # Re-running is a no-op.
    assert "marking" not in run_create_db(capsys)
    assert revision(path) == head()


def test_downgrade_removes_what_the_old_schema_cannot_hold(tmp_path):
    path = tmp_path / "d.db"
    config = alembic_config(path)
    command.upgrade(config, "head")
    con = sqlite3.connect(path)
    con.executescript(
        """
        insert into swimmers (id, name, birthdate, gender) values (1, 'A', '2016-01-01', 'M');
        insert into meets (id, name, date) values (1, 'M', '2026-07-25');
        insert into events (id, distance, stroke, course, relay) values (1, 50, 'FR', 'LCM', 0), (2, 200, 'IM', 'LCM', 1);
        insert into meet_entries (id, meet_id, swimmer_id, event_id) values (1, 1, 1, 1), (2, 1, 1, 2);
        insert into swim_times (meet_entry_id, time_seconds, dq) values (1, 36.16, 0), (2, 184.99, 0);
        """
    )
    con.commit()
    con.close()

    command.downgrade(config, "0001")

    con = sqlite3.connect(path)
    assert con.execute("select id from events").fetchall() == [(1,)]  # the relay event is gone
    assert con.execute("select time_seconds from swim_times").fetchall() == [(36.16,)]
    con.close()
