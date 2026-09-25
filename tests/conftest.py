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


def make_test_engine(path=None):
    """Never touches swim_tracker.db.

    Default: in-memory DB on one shared connection (StaticPool) so the
    TestClient's threads and the test body see the same data. With `path`: a
    throwaway file DB with a normal pool, for the live server, whose threads
    handle concurrent requests and must not share a single connection."""
    if path is None:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", database._enable_sqlite_foreign_keys)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def engine():
    eng = make_test_engine()
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
    return crud.create_swimmer(db, schemas.SwimmerCreate(name="Adella Barber", birthdate=date(2014, 5, 1), gender="F"))


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
        monkeypatch.setattr(module.pdfplumber, "open", lambda path: FakePDF(pages_by_path[str(path)]))

    return install


# --- frontend (browser) tests ----------------------------------------------


@pytest.fixture(scope="session")
def live_server():
    """Runs the real app (API + static frontend) on a free local port in a
    background thread. Which DB it talks to is decided per test by whoever sets
    app.dependency_overrides[database.get_db] (see `serve_db`)."""
    import socket
    import threading
    import time

    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            pytest.fail("live server did not start")
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def serve_db(factory):
    """Point every request (TestClient or live server) at sessions from `factory`."""

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[database.get_db] = override_get_db


@pytest.fixture(scope="session")
def browser():
    """A headless browser: the installed Chrome or Edge if present (no download
    needed), else Playwright's bundled Chromium. Skips if none is available."""
    sync_api = pytest.importorskip("playwright.sync_api")
    pw = sync_api.sync_playwright().start()
    launched = None
    for channel in ("chrome", "msedge", None):
        try:
            launched = pw.chromium.launch(channel=channel) if channel else pw.chromium.launch()
            break
        except sync_api.Error:
            continue
    if launched is None:
        pw.stop()
        pytest.skip("no browser for Playwright; run `playwright install chromium`")
    yield launched
    launched.close()
    pw.stop()


class ConfirmRecorder:
    """Answers window.confirm() dialogs and records their messages."""

    def __init__(self):
        self.messages = []
        self.accept = True

    def __call__(self, dialog):
        self.messages.append(dialog.message)
        dialog.accept() if self.accept else dialog.dismiss()


@pytest.fixture
def confirms():
    return ConfirmRecorder()


@pytest.fixture
def page(browser, live_server, session_factory, confirms):
    """A fresh browser page whose API calls hit this test's in-memory DB.
    Locale/timezone are pinned so date formatting is deterministic; a zone
    west of UTC catches dates wrongly parsed as UTC midnight."""
    serve_db(session_factory)
    context = browser.new_context(base_url=live_server, locale="en-US", timezone_id="America/Chicago")
    pg = context.new_page()
    pg.set_default_timeout(5000)
    pg.on("dialog", confirms)
    yield pg
    context.close()
    app.dependency_overrides.clear()
