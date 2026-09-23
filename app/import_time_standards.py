"""
Bulk-import time standards from PDF files into the swim tracker database.

Run this from the project root (same folder as database.py, crud.py, models.py):

    python import_time_standards.py

Handles two known PDF layouts:
  - USA Swimming Motivational Standards (organization="USA Swimming")
    Course (SCY/SCM/LCM) is embedded per-row in the Event column.
    Tiers: B, BB, A, AA, AAA, AAAA
  - MN Swimming standards, one file per course (organization="MN Swimming")
    Course is passed in per-file, since the file itself is SCY-only or LCM-only.
    Tiers: BRNZ, SLVR, GOLD, CH, ZONE

Relay events (FR-R, MED-R) are intentionally skipped - the current data
model only supports individual events. See the row-by-row notes below for
how relay rows are detected and discarded.

Both PDFs are parsed by clustering words into rows by y-position, then
bucketing each word into a column by x-position (matched against the
column header x-positions found on each page). This is more robust than
line-by-line text parsing because it isn't thrown off by wrapped labels
(e.g. "200 MED-R" wrapping "SCY" onto its own line) - a row that doesn't
resolve to a complete <distance> <stroke> [<course>] pattern in the Event
column is simply skipped, which conveniently also skips relays and
header/footer text without any special-casing.

Malformed source data (e.g. a few rows in the MN files have values like
"35:39" where a leading colon was clearly swapped for a colon-as-minutes
typo in the original PDF) is logged and skipped rather than guessed at -
check the summary at the end and consult the source PDF for anything
listed under "SKIPPED (malformed time value)".
"""

import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).parent))
from database import SessionLocal
import crud, schemas
from models import Stroke, Course


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def cluster_rows(words, tol=2.5):
    """Group words into rows by y-position ('top'), tolerating small jitter."""
    rows = []
    for w in sorted(words, key=lambda w: w["top"]):
        for row in rows:
            if abs(row["top"] - w["top"]) <= tol:
                row["words"].append(w)
                break
        else:
            rows.append({"top": w["top"], "words": [w]})
    return rows


def column_boundaries(x0_list):
    """Midpoints between sorted column header x-positions."""
    xs = sorted(x0_list)
    return [(xs[i] + xs[i + 1]) / 2 for i in range(len(xs) - 1)]


def bucket_columns(row_words, boundaries):
    """Assign each word in a row to a column index by nearest boundary, join text."""
    cols = {}
    for w in sorted(row_words, key=lambda w: w["x0"]):
        idx = sum(1 for b in boundaries if w["x0"] >= b)
        cols.setdefault(idx, []).append(w["text"])
    return {k: " ".join(v) for k, v in cols.items()}


def parse_time(raw):
    """'‌:58.59' / '1:44.09' / '36.29' -> seconds (float). None if unrecognized."""
    s = raw.replace("*", "").strip()
    m = re.match(r"^:(\d{1,2}\.\d{2})$", s)  # leading colon, no minutes
    if m:
        return float(m.group(1))
    m = re.match(r"^(\d{1,3}):(\d{2}\.\d{2})$", s)  # minutes:seconds.hundredths
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.match(r"^(\d{1,2}\.\d{2})$", s)  # plain seconds
    if m:
        return float(m.group(1))
    return None


def clean_age_group(s):
    """Strip stray 'Girls'/'Boys'/'BONUS' tokens that leak into wrapped header text."""
    s = re.sub(r"\bGirls\b", "", s)
    s = re.sub(r"\bBoys\b", "", s)
    s = re.sub(r"\bBONUS\b", "", s)
    s = re.sub(r"/\s+", "/", s)
    s = re.sub(r"\s+/", "/", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extract_season(page_text):
    m = re.search(r"(\d{4}-\d{4})", page_text)
    return m.group(1) if m else "unknown"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

class ImportStats:
    def __init__(self):
        self.inserted = 0
        self.duplicates = 0
        self.events_created = 0
        self.malformed = []  # list of (context, raw_value) strings

    def report(self, label):
        print(f"\n--- {label} ---")
        print(f"  Inserted:       {self.inserted}")
        print(f"  Already existed: {self.duplicates}")
        print(f"  New events auto-created: {self.events_created}")
        if self.malformed:
            print(f"  Skipped malformed values: {len(self.malformed)}")
            for ctx in self.malformed:
                print(f"    - {ctx}")


def get_or_create_event(db, distance, stroke, course, stats):
    event = crud.get_event(db, distance, stroke, course)
    if event is None:
        event = crud.create_event(db, schemas.EventCreate(distance=distance, stroke=stroke, course=course))
        stats.events_created += 1
    return event


def store_standard(db, event, organization, age_group, gender, standard_name, standard_rank, time_seconds, season, stats):
    existing = crud.get_time_standard(db, event.id, organization, age_group, gender, standard_name, season)
    if existing:
        stats.duplicates += 1
        return
    crud.create_time_standard(
        db,
        schemas.TimeStandardCreate(
            event_id=event.id,
            organization=organization,
            age_group=age_group,
            gender=gender,
            standard_name=standard_name,
            standard_rank=standard_rank,
            time_seconds=time_seconds,
            season=season,
        ),
    )
    stats.inserted += 1


# ---------------------------------------------------------------------------
# USA Swimming Motivational Standards parser
# ---------------------------------------------------------------------------

USA_GIRLS_ORDER = ["B", "BB", "A", "AA", "AAA", "AAAA"]
USA_BOYS_ORDER = ["AAAA", "AAA", "AA", "A", "BB", "B"]
USA_RANK = {"B": 1, "BB": 2, "A": 3, "AA": 4, "AAA": 5, "AAAA": 6}


def import_usa_standards(db, pdf_path, stats):
    with pdfplumber.open(pdf_path) as pdf:
        season = extract_season(pdf.pages[0].extract_text())
        for page in pdf.pages:
            words = page.extract_words()
            event_hdr = [w for w in words if w["text"] == "Event"]
            if not event_hdr:
                continue
            tier_words = [w for w in words if w["top"] < 80 and w["text"] in USA_GIRLS_ORDER]
            if not tier_words:
                continue
            event_x0 = event_hdr[0]["x0"]
            all_x0 = sorted(set(round(w["x0"], 1) for w in tier_words) | {event_x0})
            boundaries = column_boundaries(all_x0)
            event_idx = all_x0.index(event_x0)

            rows = cluster_rows([w for w in words if w["top"] > 60])
            current_age_group = None
            for row in rows:
                texts = [w["text"] for w in row["words"]]
                if "Girls" in texts and "Boys" in texts:
                    age_words = [
                        w["text"] for w in sorted(row["words"], key=lambda w: w["x0"])
                        if w["x0"] < event_x0 and w["text"] != "Girls"
                    ]
                    current_age_group = clean_age_group(" ".join(age_words))
                    continue

                cols = bucket_columns(row["words"], boundaries)
                evt_txt = cols.get(event_idx, "").replace("*", "").strip()
                m = re.match(r"^(\d+)\s+(FR|BK|BR|FL|IM)\s+(SCY|SCM|LCM)$", evt_txt)
                if not m:
                    continue  # relay row, wrapped continuation, or non-data text

                distance, stroke_txt, course_txt = m.groups()
                event = get_or_create_event(db, int(distance), Stroke(stroke_txt), Course(course_txt), stats)

                girls_vals = [cols.get(i, "") for i in range(0, event_idx)]
                boys_vals = [cols.get(i, "") for i in range(event_idx + 1, max(cols.keys()) + 1)]

                for name, raw in zip(USA_GIRLS_ORDER, girls_vals):
                    t = parse_time(raw)
                    if t is None:
                        if raw.strip():  # non-empty but unparseable = a real problem; blank = no standard published
                            stats.malformed.append(f"USA p{page.page_number} {current_age_group} Girls {evt_txt} {name}: {raw!r}")
                        continue
                    store_standard(db, event, "USA Swimming", current_age_group, "F", name, USA_RANK[name], t, season, stats)

                for name, raw in zip(USA_BOYS_ORDER, boys_vals):
                    t = parse_time(raw)
                    if t is None:
                        if raw.strip():
                            stats.malformed.append(f"USA p{page.page_number} {current_age_group} Boys {evt_txt} {name}: {raw!r}")
                        continue
                    store_standard(db, event, "USA Swimming", current_age_group, "M", name, USA_RANK[name], t, season, stats)


# ---------------------------------------------------------------------------
# MN Swimming standards parser (one file per course)
# ---------------------------------------------------------------------------

MN_GIRLS_ORDER = ["BRNZ", "SLVR", "GOLD", "CH", "ZONE"]
MN_BOYS_ORDER = ["ZONE", "CH", "GOLD", "SLVR", "BRNZ"]
MN_RANK = {"BRNZ": 1, "SLVR": 2, "GOLD": 3, "CH": 4, "ZONE": 5}
MN_STROKE_MAP = {"Free": Stroke.FR, "Back": Stroke.BK, "Breast": Stroke.BR, "Fly": Stroke.FL, "IM": Stroke.IM}


def import_mn_standards(db, pdf_path, course: Course, stats):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        season = extract_season(page.extract_text())
        words = page.extract_words()

        all_rows = cluster_rows(words)
        legend_row = next((row for row in all_rows if "BRNZ" in [w["text"] for w in row["words"]]
                            and "Girls" not in [w["text"] for w in row["words"]]), None)
        if legend_row is None:
            print(f"  WARNING: could not find the BRNZ/SLVR/GOLD/CH/ZONE legend row in {pdf_path} - skipping file")
            return

        tier_words = [w for w in legend_row["words"] if w["text"] in MN_GIRLS_ORDER]
        event_hdr = [w for w in legend_row["words"] if w["text"] == "Event"]
        event_x0 = event_hdr[0]["x0"]
        all_x0 = sorted(set(round(w["x0"], 1) for w in tier_words) | {event_x0})
        boundaries = column_boundaries(all_x0)
        event_idx = all_x0.index(event_x0)

        current_age_group = None
        for row in all_rows:
            if row is legend_row:
                continue
            texts = [w["text"] for w in row["words"]]
            if "Girls" in texts and "Boys" in texts:
                age_words = [
                    w["text"] for w in sorted(row["words"], key=lambda w: w["x0"])
                    if w["x0"] < event_x0 and w["text"] != "Girls"
                ]
                current_age_group = clean_age_group(" ".join(age_words))
                continue

            cols = bucket_columns(row["words"], boundaries)
            evt_txt = cols.get(event_idx, "").strip()
            m = re.match(r"^(\d+)\s+(Free|Back|Breast|Fly|IM)$", evt_txt)
            if not m:
                continue

            distance, stroke_txt = m.groups()
            event = get_or_create_event(db, int(distance), MN_STROKE_MAP[stroke_txt], course, stats)

            girls_vals = [cols.get(i, "") for i in range(0, event_idx)]
            boys_vals = [cols.get(i, "") for i in range(event_idx + 1, max(cols.keys()) + 1)]

            for name, raw in zip(MN_GIRLS_ORDER, girls_vals):
                t = parse_time(raw)
                if t is None:
                    if raw.strip():
                        stats.malformed.append(f"MN {course.value} {current_age_group} Girls {evt_txt} {name}: {raw!r}")
                    continue
                store_standard(db, event, "MN Swimming", current_age_group, "F", name, MN_RANK[name], t, season, stats)

            for name, raw in zip(MN_BOYS_ORDER, boys_vals):
                t = parse_time(raw)
                if t is None:
                    if raw.strip():
                        stats.malformed.append(f"MN {course.value} {current_age_group} Boys {evt_txt} {name}: {raw!r}")
                    continue
                store_standard(db, event, "MN Swimming", current_age_group, "M", name, MN_RANK[name], t, season, stats)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

FILES = {
    "USA Swimming Motivational Standards": ("usa", "time_standards/USA_Swimming_Motivational_Standards.pdf", None),
    "MN Swimming SCY Standards": ("mn", "time_standards/MN_Swimming_SCY_Standards.pdf", Course.SCY),
    "MN Swimming LCM Standards": ("mn", "time_standards/MN_Swimming_LCM_Standards.pdf", Course.LCM),
}


def main():
    db = SessionLocal()
    try:
        for label, (kind, filename, course) in FILES.items():
            path = Path(filename)
            if not path.exists():
                print(f"SKIPPING {label}: file not found at {path.resolve()} "
                      f"(place it next to this script, or edit the FILES dict at the bottom of the script)")
                continue
            stats = ImportStats()
            print(f"Importing {label} ...")
            if kind == "usa":
                import_usa_standards(db, path, stats)
            else:
                import_mn_standards(db, path, course, stats)
            stats.report(label)
    finally:
        db.close()


if __name__ == "__main__":
    main()
