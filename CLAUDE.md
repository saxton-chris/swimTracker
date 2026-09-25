# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A FastAPI + SQLAlchemy 2.0 (SQLite) backend for tracking a swimmer's meet results against USA Swimming and MN Swimming time standards, with a small no-build web frontend served by the same app. Ruff handles linting and formatting (`ruff.toml` at the repo root).

## Commands

All code lives in `app/` and uses flat (non-package) imports (`import crud, schemas`, `from routers import ...`), so **run everything from inside `app/`**:

```powershell
# setup (venv lives at repo root)
python -m venv venv; .\venv\Scripts\Activate.ps1; pip install -r requirements.txt

cd app
python create_db.py                     # create tables (create_all only; no migrations)
uvicorn main:app --reload               # web UI at /, API docs at /docs, health check at /health
python import_time_standards.py         # bulk-load standards from app/time_standards/*.pdf
python import_meet_results.py results.pdf --meet-id 3 [--team WEST-MN]
```

Tests run from the **repo root** (`pytest.ini` puts `app/` on the path and enables coverage):

```powershell
pip install -r requirements-dev.txt
pytest                                             # full suite + coverage report
pytest tests/test_api.py::test_event_duplicate     # single test
pytest -m "not ui"                                 # skip the browser tests
ruff check .                                       # lint (add --fix for safe auto-fixes)
ruff format .                                      # format
```

Tests use an in-memory SQLite DB (`tests/conftest.py`, `StaticPool`) and override `database.get_db`; they never touch `swim_tracker.db`. Frontend tests (marked `ui`) use Playwright against a live uvicorn thread (`live_server` fixture). They launch the installed Chrome or Edge, falling back to Playwright's Chromium, and skip if no browser is found. They use a temporary SQLite *file* instead of `StaticPool`, because the page sends parallel requests that the server answers on separate threads, and those threads can't safely share a single connection. The PDF importers are tested by monkeypatching `pdfplumber.open` with `FakePDF`/`FakePage` objects built from `{"text", "x0", "top"}` word dicts, and their `main()` functions by patching the module's `SessionLocal`.

There is no migration tool (no Alembic). Schema changes to `models.py` require deleting `app/swim_tracker.db` and re-running `create_db.py` + the import scripts. The `*.db` file and `time_standards/` PDF folder are gitignored.

## Architecture

Layering per resource: `routers/<resource>.py` (HTTP, validation of FK existence, duplicate checks → 404/400) → `crud.py` (all DB queries, one module for every model) → `models.py` (SQLAlchemy ORM). `schemas.py` holds Pydantic `XCreate` / `XOut` / `XUpdate` models. Routers are registered in `main.py`.

- **DB path** is anchored in `database.py` next to the module, so uvicorn and the import scripts share one file regardless of CWD. SQLite foreign keys are enabled via a per-connection `PRAGMA`.
- **Data model**: `Swimmer`, `Meet` (`date` is the first day; optional `end_date` is the last day of a multi-day meet, validated `>= date` on create and on PATCH against the stored values. A results file covering all days imports into the one meet; per-swim days aren't tracked because Hy-Tek results PDFs don't give them), `Event` (unique on distance+stroke+course; `name` is a computed property, not a column) → `MeetEntry` (one swimmer, one event, one meet; unique triple) → `SwimTime` (at most one per `MeetEntry`, `time_seconds` as float). `TimeStandard` is independent reference data keyed by event/organization/age_group/gender/standard_name/season, with `standard_rank` to order tiers within an organization.
- **Times are stored as float seconds**, never formatted strings; format at the display layer.
- **Gender** is constrained to `"F"`/`"M"` in schemas so swimmers match `TimeStandard.gender`.
- **PATCH pattern**: `XUpdate` schemas have all-optional fields; `crud._apply_update` applies only `model_dump(exclude_unset=True)`. NOT NULL columns use the `_reject_null` validator so a field can be omitted but not explicitly set to null.
- **DELETE** endpoints exist for swimmers, meets, meet entries, and swim times (204, or 404 if missing). Deletes cascade through ORM relationships (`cascade="all, delete"`): swimmer/meet → its meet entries → their swim time. Events and time standards have no delete endpoint.
- **Creating a duplicate** (e.g. a second `SwimTime` for a meet entry) returns 400 pointing to the PATCH endpoint rather than upserting.
- `models.py` imports `date as date_type` deliberately: under Python 3.14 lazy annotations, a column named `date` annotated with bare `date` would resolve to itself.

## Frontend

`app/static/` (`index.html`, `app.js`, `styles.css`) is plain HTML/JS with no build step or dependencies. `main.py` serves `index.html` at `/` and mounts the directory at `/static`. The page calls the JSON API with `fetch`, loads every list on startup, and reloads them all after each change (the dataset is small). It has four tabs: Entries & Results, Swimmers, Meets, and Time Standards.

- Time Standards is read-only. `GET /time_standards/sets` lists the organization/season pairs that have data, and the page shows exactly one at a time. It starts on a disabled "Select a standard…" placeholder, which is never remembered across loads. A set's rows (`GET /time_standards/?organization=&season=`) are fetched when it's first selected and cached for the page's lifetime, not reloaded with the other lists. The Distance/Stroke/Course/Gender filters and the Age groups multi-select offer only values that set covers (MN and USA age groups differ). Age groups is a `<details>` checkbox dropdown: none ticked means all, and ticked groups carry over to another set only if it has them. The table groups rows by age group (ordered by the first number in the name), with one column per tier in `standard_rank` order. Age-group headings are collapsible only when more than one is shown.
- Collapsing (meets on Entries, age groups on Time Standards) shares `storedSet()` and `groupToggle()` in `app.js`. Each keeps its own `localStorage` key: `swimTracker.collapsedMeets` holds meet ids, and `swimTracker.collapsedAgeGroups` holds `org|season|age group`.

- Meets are listed oldest first by start date everywhere: the Meets tab, the dropdowns, and the Entries table. The Entries table groups rows under one `tr.meet-heading` per meet (name, dates, location) and has no Meet/Date columns. New-entry and import dialogs default to the newest meet when the table isn't filtered. Each heading's meet name is a disclosure button (`aria-expanded`) that collapses that meet's rows. Collapsed meet ids are kept in `localStorage` (`swimTracker.collapsedMeets`, per browser, wrapped in try/catch so the page works without storage).
- Meet entries and their result are edited in one dialog. The event is chosen by distance/stroke/course and created through `POST /events/` if it doesn't exist. The time is entered as `ss.xx` or `m:ss.xx` and sent as float seconds. Clearing the time deletes the `SwimTime`.
- Deletes use `confirm()` and say how many entries and results the cascade will remove.
- "Import results" on the Entries tab uploads a Hy-Tek results PDF for a chosen meet to `POST /meets/{id}/import-results`. The PDF is the raw request body (`Content-Type: application/pdf`, no multipart, so no `python-multipart` dependency). The endpoint runs the same `parse_pdf` + `import_results` as the CLI script, with no team filter, and returns a count summary that the page shows as a toast.
- All user data is rendered with `textContent`, never `innerHTML`.
- Styling uses West Express colors: orange `#F2661B` and black as primary, purple `#5A2D82` as secondary, set as CSS custom properties at the top of `styles.css`, with a dark-mode override. Fonts are Barlow Condensed and Barlow from Google Fonts, falling back to system fonts when offline. Times are shown in a scoreboard-style `.clock` element. Below 640px the entries table stacks each row, and the swimmer/meet tables hide the `.c-birthdate`, `.c-notes`, and `.c-location` columns.
- Tests: `tests/test_frontend_js.py` calls `app.js`'s helpers (`parseTime`, `formatTime`, etc.) directly in a browser page, `tests/test_frontend_ui.py` drives the UI end to end, and `tests/test_frontend_static.py` checks that every element id `app.js` looks up exists in `index.html`.

## Import scripts

Both scripts use `pdfplumber` and parse PDFs by clustering words into rows by y-position and bucketing into columns by x-position, rather than line-by-line text. They write through `crud`/`schemas` (not raw SQL), are idempotent (check for existing rows before inserting), and print a summary of skipped rows instead of guessing.

- `import_time_standards.py`: handles the USA Swimming Motivational Standards layout (course per row; tiers B–AAAA) and MN Swimming per-course files (tiers BRNZ/SLVR/GOLD/CH/ZONE). Source filenames are in the `FILES` dict at the bottom.
- `import_meet_results.py`: parses Hy-Tek Meet Manager two-column "Results" PDFs. Also used by the web import endpoint (see Frontend). The `Meet` must already exist (`--meet-id`). Swimmers are matched by "First Last" against existing rows only — never auto-created.
- The MN SCY PDF has three typos (11-12 Boys 50 Free SLVR `35:39`, BRNZ `41:09`, 50 Breast ZONE `33:29`) that the importer skips as malformed. After a fresh import, add them by hand as 35.39, 41.09, and 33.29 seconds, season 2025-2026.
- Both intentionally skip relays (model supports individual events only); the results importer also skips Time Trials, DQs, NS, and splits.
