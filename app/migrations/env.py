"""Alembic environment: migrates swim_tracker.db (or the file given with `-x db=...`).

Run from app/:
    alembic upgrade head                      # bring the database up to date
    alembic -x db=C:\\path\\copy.db upgrade head
    alembic revision --autogenerate -m "..."  # after changing models.py
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, event

import database
from models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def db_url():
    """Which database to migrate: `-x db=path` on the command line, else the URL a caller
    put in config.attributes["url"] (create_db.py does), else the app's swim_tracker.db."""
    path = context.get_x_argument(as_dictionary=True).get("db")
    if path:
        return f"sqlite:///{path}"
    return config.attributes.get("url") or f"sqlite:///{database.DB_PATH}"


def run_migrations_offline():
    """Emit SQL to stdout instead of running it (alembic upgrade head --sql)."""
    context.configure(
        url=db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(db_url())
    # SQLite batch migrations rebuild a table (create new, copy rows, drop old, rename), and
    # dropping the old table would cascade-delete child rows while foreign keys are enforced.
    # So FKs stay OFF during migrations (the app's own connections turn them on).
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=OFF"))
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite can't ALTER most column properties; batch mode rebuilds the table instead.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
