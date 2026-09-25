# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A FastAPI + SQLAlchemy 2.0 (SQLite) backend for tracking a swimmer's meet results against USA Swimming and MN Swimming time standards. There is no frontend, test suite, or linter configured yet.

## Commands

All code lives in `app/` and uses flat (non-package) imports (`import crud, schemas`, `from routers import ...`), so **run everything from inside `app/`**:

```powershell
# setup (venv lives at repo root)
python -m venv venv; .\venv\Scripts\Activate.ps1; pip install -r requirements.txt

cd app
python create_db.py                     # create tables (create_all only; no migrations)
uvicorn main:app --reload               # run API; interactive docs at /docs
python import_time_standards.py         # bulk-load standards from app/time_standards/*.pdf
python import_meet_results.py results.pdf --meet-id 3 [--team WEST-MN]
```

There is no migration tool (no Alembic). Schema changes to `models.py` require deleting `app/swim_tracker.db` and re-running `create_db.py` + the import scripts. The `*.db` file and `time_standards/` PDF folder are gitignored.

## Architecture

Layering per resource: `routers/<resource>.py` (HTTP, validation of FK existence, duplicate checks → 404/400) → `crud.py` (all DB queries, one module for every model) → `models.py` (SQLAlchemy ORM). `schemas.py` holds Pydantic `XCreate` / `XOut` / `XUpdate` models. Routers are registered in `main.py`.

- **DB path** is anchored in `database.py` next to the module, so uvicorn and the import scripts share one file regardless of CWD. SQLite foreign keys are enabled via a per-connection `PRAGMA`.
- **Data model**: `Swimmer`, `Meet`, `Event` (unique on distance+stroke+course; `name` is a computed property, not a column) → `MeetEntry` (one swimmer, one event, one meet; unique triple) → `SwimTime` (at most one per `MeetEntry`, `time_seconds` as float). `TimeStandard` is independent reference data keyed by event/organization/age_group/gender/standard_name/season, with `standard_rank` to order tiers within an organization.
- **Times are stored as float seconds**, never formatted strings; format at the display layer.
- **Gender** is constrained to `"F"`/`"M"` in schemas so swimmers match `TimeStandard.gender`.
- **PATCH pattern**: `XUpdate` schemas have all-optional fields; `crud._apply_update` applies only `model_dump(exclude_unset=True)`. NOT NULL columns use the `_reject_null` validator so a field can be omitted but not explicitly set to null.
- **Creating a duplicate** (e.g. a second `SwimTime` for a meet entry) returns 400 pointing to the PATCH endpoint rather than upserting.
- `models.py` imports `date as date_type` deliberately: under Python 3.14 lazy annotations, a column named `date` annotated with bare `date` would resolve to itself.

## Import scripts

Both scripts use `pdfplumber` and parse PDFs by clustering words into rows by y-position and bucketing into columns by x-position, rather than line-by-line text. They write through `crud`/`schemas` (not raw SQL), are idempotent (check for existing rows before inserting), and print a summary of skipped rows instead of guessing.

- `import_time_standards.py`: handles the USA Swimming Motivational Standards layout (course per row; tiers B–AAAA) and MN Swimming per-course files (tiers BRNZ/SLVR/GOLD/CH/ZONE). Source filenames are in the `FILES` dict at the bottom.
- `import_meet_results.py`: parses Hy-Tek Meet Manager two-column "Results" PDFs. The `Meet` must already exist (`--meet-id`). Swimmers are matched by "First Last" against existing rows only — never auto-created.
- Both intentionally skip relays (model supports individual events only); the results importer also skips Time Trials, DQs, NS, and splits.
