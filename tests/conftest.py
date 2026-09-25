from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import crud
import database
import schemas
from main import app
from models import Base, Course, Stroke


@pytest.fixture
def engine():
    # In-memory DB shared across connections (StaticPool) so the TestClient's
    # threads and the test body see the same data. Never touches swim_tracker.db.
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(eng, "connect", database._enable_sqlite_foreign_keys)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[database.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- sample data -----------------------------------------------------------

@pytest.fixture
def swimmer(db):
    return crud.create_swimmer(
        db, schemas.SwimmerCreate(name="Adella Barber", birthdate=date(2014, 5, 1), gender="F")
    )


@pytest.fixture
def meet(db):
    return crud.create_meet(db, schemas.MeetCreate(name="Winter Invite", date=date(2026, 1, 10)))


@pytest.fixture
def swim_event(db):
    return crud.create_event(db, schemas.EventCreate(distance=50, stroke=Stroke.FR, course=Course.SCY))


@pytest.fixture
def meet_entry(db, swimmer, meet, swim_event):
    return crud.create_meet_entry(
        db, schemas.MeetEntryCreate(meet_id=meet.id, swimmer_id=swimmer.id, event_id=swim_event.id)
    )


# --- fake pdfplumber -------------------------------------------------------

def word(text, x0, top):
    return {"text": text, "x0": x0, "top": top}


class FakePage:
    def __init__(self, words, text="", page_number=1):
        self._words = words
        self._text = text
        self.page_number = page_number

    def extract_words(self):
        return self._words

    def extract_text(self):
        return self._text


class FakePDF:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_pdfplumber(monkeypatch):
    """Returns a function that makes `module.pdfplumber.open(path)` yield the
    pages registered for that path."""
    def install(module, pages_by_path):
        monkeypatch.setattr(
            module.pdfplumber, "open", lambda path: FakePDF(pages_by_path[str(path)])
        )
    return install
