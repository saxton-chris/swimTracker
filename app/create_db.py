"""Create swim_tracker.db, or bring an existing one up to date. Safe to re-run.

Runs the Alembic migrations in migrations/ (same as `alembic upgrade head`).
A database made before the project used Alembic (tables but no recorded
revision) is first marked as revision 0001, the schema it already has, then upgraded.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

import database

PRE_ALEMBIC_REVISION = "0001"


def main():
    engine = database.engine
    config = Config(Path(__file__).parent / "alembic.ini")
    # Migrate exactly the database inspected here (migrations/env.py reads this).
    config.attributes["url"] = engine.url.render_as_string(hide_password=False)

    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names()) - {"alembic_version"}
        current = MigrationContext.configure(conn).get_current_revision()
    engine.dispose()

    if tables and current is None:
        print(f"Existing database without migration history: marking it as revision {PRE_ALEMBIC_REVISION}.")
        command.stamp(config, PRE_ALEMBIC_REVISION)
    command.upgrade(config, "head")
    print(f"Database is up to date: {engine.url.database}")


if __name__ == "__main__":
    main()
