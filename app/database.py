from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# Anchor the DB file next to this module so every entry point (uvicorn, the
# import scripts, create_db.py) uses the same file regardless of the CWD.
DB_PATH = Path(__file__).parent / "swim_tracker.db"

engine = create_engine(f"sqlite:///{DB_PATH}")
SessionLocal = sessionmaker(bind=engine)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    # SQLite ignores FOREIGN KEY constraints unless this is set per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Route parameter type for "a DB session for this request": `db: DbSession`.
DbSession = Annotated[Session, Depends(get_db)]
