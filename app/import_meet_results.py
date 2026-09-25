"""
Import swim results from a Hy-Tek Meet Manager "Results" PDF into
meet_entries + swim_times.

Run from the app/ folder (same folder as main.py):

    python import_meet_results.py results.pdf --meet-id 3

Requires the Meet to already exist (create it first via POST /meets/ or
DB Browser) - the PDF has no reliable meet date printed on it (only a
report-generation timestamp), so the meet_id must be given explicitly
rather than guessed.

What gets imported:
  - Individual results (placed rows).
  - DQs ("--- Name age TEAM DQ [time]"), with the reason Hy-Tek prints on
    the next line (e.g. "False start") and the time swum, if shown.
  - Exhibition swims ("--- Name age TEAM X59.34": swum and timed, not scored),
    noted as "exhibition".
  - Relays: each relay swimmer gets a result with the team's time (or DQ), which
    leg they swam, and their own split for it. Splits are used only when the
    four leg values add up to the team time (or are cumulative up to it);
    otherwise the split is left blank rather than guessed.

What is skipped, by design, and counted in the summary:
  - "Time Trial" swims - unranked re-swims that share the same event/swimmer
    as the real race, and only one SwimTime per MeetEntry is allowed.
  - No-shows (NS) and scratches (SCR) - he didn't race.
  - Splits of individual races - not part of the schema.

Swimmer matching: the PDF prints "Last, First M" (e.g. "Barber, Adella F").
This is converted to "First Last" (middle initial dropped) and matched
case-insensitively against your existing swimmers table - being IN THAT
TABLE is what gates the import, not which team the PDF lists a swimmer
under. A name that doesn't match an existing swimmer is never guessed at
or auto-created; add the swimmer first (POST /swimmers/), then re-run.
Pass --team to additionally require a specific team abbreviation (e.g.
WEST-MN) - useful insurance against a same-named swimmer on another team,
since Swimmer has no team field of its own to cross-check against.

Safe to re-run: every insert checks for an existing meet_entry / swim_time
first, so re-running after adding a missed swimmer won't duplicate
anything already imported.
"""

import argparse
import re
import sys
from itertools import pairwise
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).parent))
import crud
import schemas
from database import SessionLocal
from models import Course, Stroke

# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

COLUMN_SPLIT_X = 300  # left column words have x0 < this; right column >= this

EVENT_RE = re.compile(
    r"^(?:Event\s+\d+\s+)?"
    r"(?P<gender>Girls|Boys|Women|Men|Mixed)\s+"
    r"(?P<age>\d+\s*&\s*(?:Under|Over)|\d+-\d+|Open|Senior)\s+"
    r"(?P<distance>\d+)\s+"
    r"(?P<course>LC|SC)\s+(?P<unit>Meter|Yard)\s+"
    r"(?P<stroke>Freestyle|Backstroke|Breaststroke|Butterfly|Individual Medley|IM|Medley)"
    r"(?P<relay>\s+Relay)?"
    r"(?P<timetrial>\s+Time Trial)?\s*$"
)
# Anything shaped like an event header, even one EVENT_RE can't fully parse.
# Used to close out the previous event so its rows aren't mis-attributed.
EVENT_HEADER_LIKE_RE = re.compile(r"^(?:Event\s+\d+\s+)?(?:Girls|Boys|Women|Men|Mixed)\b.*\b(?:Yard|Meter)\b")
TEAM_RE = re.compile(r"^[A-Z][A-Za-z]{1,5}-[A-Z]{2}$")
TIME_RE = re.compile(r"^X?(\d{1,2}:)?\d{1,2}\.\d{2}$")
RELAY_LETTER_RE = re.compile(r"^[A-Z]$")
# "1) Saxton, Alistair B M10 2) ..." - mixed relays prefix the age with W/M.
RELAY_SWIMMER_RE = re.compile(r"(\d)\)\s*(.+?)\s+[WM]?(\d{1,2})(?=\s+\d\)|\s*$)")
# Page furniture that must never be mistaken for a DQ reason.
NOT_A_REASON_RE = re.compile(r"Site License|HY-TEK|Meet Manager|^Results\b", re.IGNORECASE)

STROKE_MAP = {
    "Freestyle": Stroke.FR,
    "Backstroke": Stroke.BK,
    "Breaststroke": Stroke.BR,
    "Butterfly": Stroke.FL,
    "Individual Medley": Stroke.IM,
    "IM": Stroke.IM,
}
RELAY_STROKE_MAP = {"Freestyle": Stroke.FR, "Medley": Stroke.IM}  # a medley relay is stored as IM + relay
COURSE_MAP = {
    ("LC", "Meter"): Course.LCM,
    ("SC", "Meter"): Course.SCM,
    ("SC", "Yard"): Course.SCY,
}


def new_skip_counts():
    return {"unsupported_event": 0, "no_show_or_scratch": 0, "unparsed_row": 0}


def cluster_rows(words, tol=2.5):
    """Group words into rows by y-position ('top'), tolerating small jitter."""
    # Words are visited top-down and each row's anchor is more than `tol` below
    # the previous one, so only the most recent row can ever match - O(n).
    rows = []
    for w in sorted(words, key=lambda w: w["top"]):
        if rows and w["top"] - rows[-1]["top"] <= tol:
            rows[-1]["words"].append(w)
        else:
            rows.append({"top": w["top"], "words": [w]})
    return rows


def parse_time(raw):
    """'1:23.49' / '43.23' (optionally 'X'-prefixed or in parentheses) -> seconds. None if unrecognized."""
    s = raw.strip("()").lstrip("X")
    m = re.match(r"^(\d{1,2}):(\d{2}\.\d{2})$", s)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.match(r"^(\d{1,2}\.\d{2})$", s)
    if m:
        return float(m.group(1))
    return None


def _last_time(words):
    """The last time-shaped token in `words`, as seconds (None if there isn't one)."""
    return next((parse_time(w["text"]) for w in reversed(words) if TIME_RE.match(w["text"])), None)


def parse_result_row(words):
    """words: this row's words, any order. Returns a result dict, or None if
    this isn't a real numbered individual result (relay rows, header rows,
    splits lines, and standard-tag lines all correctly return None here)."""
    words = sorted(words, key=lambda w: w["x0"])
    if not words or not re.match(r"^\d+$", words[0]["text"]):
        return None

    team_idx = next((i for i, w in enumerate(words) if TEAM_RE.match(w["text"])), None)
    if team_idx is None or team_idx < 2:
        # < 2 means there's no room for any name words before the team token -
        # this is what a relay team's own result row looks like (place, team, ...)
        return None

    age_word = words[team_idx - 1]["text"]
    if not re.match(r"^\d{1,2}$", age_word):
        return None

    # Hy-Tek rows can be "... Team SeedTime FinalsTime Points"; the result is
    # the LAST time on the row (a seed, when present, comes first).
    time_seconds = _last_time(words[team_idx + 1 :])
    if time_seconds is None:
        return None

    return {
        "place": words[0]["text"],
        "name": " ".join(w["text"] for w in words[1 : team_idx - 1]),
        "age": int(age_word),
        "team": words[team_idx]["text"],
        "time_seconds": time_seconds,
    }


def parse_unplaced_row(words):
    """An individual '---' row: '--- Name age TEAM DQ [time]', '--- Name age TEAM X59.34'
    (exhibition), or '... NS' / '... SCR'. Returns the fields plus 'mark' (DQ/NS/SCR or None),
    or None if the row doesn't have that shape."""
    words = sorted(words, key=lambda w: w["x0"])
    team_idx = next((i for i, w in enumerate(words) if TEAM_RE.match(w["text"])), None)
    if not words or words[0]["text"] != "---" or team_idx is None or team_idx < 3:
        return None
    age_word = words[team_idx - 1]["text"]
    if not re.match(r"^\d{1,2}$", age_word):
        return None
    after = words[team_idx + 1 :]
    mark = next((w["text"] for w in after if w["text"] in ("DQ", "NS", "SCR", "DNF", "DFS")), None)
    return {
        "place": None,
        "name": " ".join(w["text"] for w in words[1 : team_idx - 1]),
        "age": int(age_word),
        "team": words[team_idx]["text"],
        "time_seconds": _last_time(after),
        "mark": mark,
        "exhibition": mark is None and any(w["text"].startswith("X") and TIME_RE.match(w["text"]) for w in after),
    }


def parse_relay_team_row(words):
    """'1 WEST-MN A 2:39.11 40' or '--- NOR-MN A DQ 4:28.60' -> team fields, else None."""
    words = sorted(words, key=lambda w: w["x0"])
    if len(words) < 3 or not TEAM_RE.match(words[1]["text"]) or not RELAY_LETTER_RE.match(words[2]["text"]):
        return None
    first = words[0]["text"]
    if not (first.isdigit() or first == "---"):
        return None
    texts = {w["text"] for w in words[3:]}
    return {
        "place": first if first.isdigit() else None,
        "team": words[1]["text"],
        "dq": "DQ" in texts,
        "no_show": bool(texts & {"NS", "SCR"}),
        "time_seconds": _last_time(words[3:]),
        "dq_reason": None,
        "swimmers": [],  # (leg, "Last, First M", age)
        "splits": [],  # seconds, as printed
    }


def relay_leg_splits(splits, team_time):
    """Each leg's own split, or None when the printed splits can't be matched to 4 legs.
    Hy-Tek prints either per-leg splits (they add up to the team time) or cumulative
    ones (the last equals the team time)."""
    if team_time is None or len(splits) != 4:
        return None
    if abs(sum(splits) - team_time) < 0.05:
        return splits
    if abs(splits[-1] - team_time) < 0.05 and splits == sorted(splits):
        return [splits[0]] + [round(b - a, 2) for a, b in pairwise(splits)]
    return None


def _is_reason(text):
    """Could this row be the DQ reason Hy-Tek prints under a DQ?"""
    return bool(
        text
        and not text.startswith("---")
        and not re.match(r"^\d+\)?\s", text)  # a placed row or a relay swimmer list
        and not all(parse_time(t) is not None for t in text.split())  # a splits line
        and not EVENT_HEADER_LIKE_RE.match(text.strip("()"))
        and not NOT_A_REASON_RE.search(text)
    )


def process_column(rows, skip_counts, state=None):
    """rows: one column's row dicts, in top order. Returns parsed individual
    result dicts; relay teams are collected in state["relay_teams"].

    `state` carries the current event (and relay team) between calls: Hy-Tek
    doesn't repeat an event's header when its results flow from the bottom of
    the left column into the right column, or onto the next page, so parse_pdf
    passes the same dict for every column in reading order."""
    if state is None:
        state = {"event": None}
    state.setdefault("relay_teams", [])
    state.setdefault("relay_team", None)
    last_dq = None  # a DQ's reason is on the very next row of the same column
    current_event = state["event"]
    results = []

    for row in rows:
        words = sorted(row["words"], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in words)
        # Page-top continuation headers are parenthesized: "(Boys 9-10 50 LC Meter Freestyle)"
        header_text = text[1:-1] if text.startswith("(") and text.endswith(")") else text

        pending_dq, last_dq = last_dq, None
        if pending_dq is not None and _is_reason(text):
            pending_dq["dq_reason"] = text
            continue

        m = EVENT_RE.match(header_text)
        # EVENT_RE accepts any LC/SC + Meter/Yard pairing, but "LC Yard" isn't a
        # real course - let it fall through to the unrecognized-header warning.
        if m and (m.group("course"), m.group("unit")) in COURSE_MAP:
            relay = bool(m.group("relay"))
            strokes = RELAY_STROKE_MAP if relay else STROKE_MAP
            if m.group("timetrial") or m.group("stroke") not in strokes:
                current_event = None  # unsupported block - its rows get skipped below
            else:
                current_event = {
                    "distance": int(m.group("distance")),
                    "stroke": strokes[m.group("stroke")],
                    "course": COURSE_MAP[(m.group("course"), m.group("unit"))],
                    "relay": relay,
                }
            state["relay_team"] = None
            continue

        if EVENT_HEADER_LIKE_RE.match(header_text):
            # A header we can't parse - stop attributing rows to the previous event.
            print(f"  WARNING: unrecognized event header, skipping its rows: {text!r}")
            current_event = None
            state["relay_team"] = None
            continue

        if text.startswith("Name") or text.startswith("Team"):
            continue  # column sub-header row

        numbered_or_unplaced = bool(words) and (re.match(r"^\d+$", words[0]["text"]) or words[0]["text"] == "---")
        if current_event is None:
            if numbered_or_unplaced:
                skip_counts["unsupported_event"] += 1  # Time Trial or unrecognized event
            continue

        if current_event["relay"]:
            team = parse_relay_team_row(words)
            if team is not None:
                if team["no_show"]:
                    skip_counts["no_show_or_scratch"] += 1
                    state["relay_team"] = None
                    continue
                team["event"] = current_event
                state["relay_teams"].append(team)
                state["relay_team"] = team
                if team["dq"]:
                    last_dq = team
                continue
            relay_team = state["relay_team"]
            if relay_team is None:
                continue
            swimmers = RELAY_SWIMMER_RE.findall(text)
            if swimmers and re.match(r"^\d\)", text):
                relay_team["swimmers"] += [(int(leg), name, int(age)) for leg, name, age in swimmers]
            elif text and all(parse_time(t) is not None for t in text.split()):
                relay_team["splits"] += [parse_time(t) for t in text.split()]
            continue

        if words and words[0]["text"] == "---":
            parsed = parse_unplaced_row(words)
            if (
                parsed is None
                or parsed["mark"] in ("NS", "SCR", "DNF", "DFS")
                or (parsed["mark"] is None and not parsed["exhibition"])
            ):
                skip_counts["no_show_or_scratch"] += 1
                continue
            parsed["dq"] = parsed.pop("mark") == "DQ"
            parsed["dq_reason"] = None
            parsed["event"] = current_event
            results.append(parsed)
            if parsed["dq"]:
                last_dq = parsed
            continue

        parsed = parse_result_row(words)
        if parsed is None:
            if words and re.match(r"^\d+$", words[0]["text"]):
                skip_counts["unparsed_row"] += 1  # looked numbered but didn't fit the expected shape
            continue  # otherwise: a splits line or standard-tag line - not an error

        parsed.update(event=current_event, dq=False, dq_reason=None, exhibition=False)
        results.append(parsed)

    state["event"] = current_event
    return results


def relay_results(team):
    """One result per swimmer on a relay team: the team's time/DQ plus their leg and split."""
    legs = relay_leg_splits(team["splits"], team["time_seconds"])
    return [
        {
            "place": team["place"],
            "name": name,
            "age": age,
            "team": team["team"],
            "time_seconds": team["time_seconds"],
            "event": team["event"],
            "dq": team["dq"],
            "dq_reason": team["dq_reason"],
            "exhibition": False,
            "relay_leg": leg,
            "split_seconds": legs[leg - 1] if legs and 1 <= leg <= 4 else None,
        }
        for leg, name, age in team["swimmers"]
    ]


def parse_pdf(path):
    all_results = []
    skip_counts = new_skip_counts()

    state = {"event": None}  # shared so an event continues across columns and pages

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            left = [w for w in words if w["x0"] < COLUMN_SPLIT_X]
            right = [w for w in words if w["x0"] >= COLUMN_SPLIT_X]
            for col_words in (left, right):
                all_results.extend(process_column(cluster_rows(col_words), skip_counts, state))

    for team in state.get("relay_teams", []):
        all_results.extend(relay_results(team))
    return all_results, skip_counts


# ---------------------------------------------------------------------------
# Swimmer name matching
# ---------------------------------------------------------------------------


def pdf_name_to_first_last(pdf_name):
    """'Barber, Adella F' -> 'Adella Barber' (middle initial dropped)."""
    if "," not in pdf_name:
        return None
    last, rest = pdf_name.split(",", 1)
    first = rest.strip().split(" ")[0]
    return f"{first.strip()} {last.strip()}"


def build_swimmer_index(db):
    """{'first last' (lowercased): Swimmer} for every swimmer in the DB."""
    return {s.name.strip().lower(): s for s in crud.get_swimmers(db)}


# ---------------------------------------------------------------------------
# Database import
# ---------------------------------------------------------------------------


def get_or_create_event(db, distance, stroke, course, relay, stats):
    event = crud.get_event(db, distance, stroke, course, relay)
    if event is None:
        event = crud.create_event(db, schemas.EventCreate(distance=distance, stroke=stroke, course=course, relay=relay))
        stats["events_created"] += 1
    return event


def new_stats():
    return {
        "events_created": 0,
        "meet_entries_created": 0,
        "times_imported": 0,
        "times_already_existed": 0,
        "would_import": 0,
    }


def result_notes(r):
    """'Imported from meet results PDF, place 25' (or ', exhibition')."""
    notes = "Imported from meet results PDF"
    if r.get("exhibition"):
        return f"{notes}, exhibition"
    if r.get("place"):
        return f"{notes}, place {r['place']}"
    return notes


def import_results(db, results, meet_id, team_filter, stats, unmatched_names, dry_run):
    """Imports any result whose swimmer name matches an existing row in your
    swimmers table - that match is the actual gate, not the team abbreviation
    printed in the PDF. team_filter is optional extra insurance: if given, a
    name has to match AND be on that team to import. Leave it unset to import
    for every matched swimmer regardless of which team the PDF lists them
    under (useful if your swimmers table includes anyone who's ever swum
    unattached, transferred teams mid-season, etc.).

    Worth knowing: since Swimmer has no team field to cross-check against,
    a very large results file (a full state meet, hundreds of swimmers) has
    some chance of two different clubs sharing a same-named swimmer. Pass
    --team to rule that out if your swimmers table ever has a name that's
    common enough to worry about.
    """
    if crud.get_meet_by_id(db, meet_id) is None:
        print(f"ERROR: no meet exists with id={meet_id}. Create it first (POST /meets/), then re-run.")
        sys.exit(1)

    swimmer_index = build_swimmer_index(db)

    for r in results:
        if team_filter is not None and r["team"] != team_filter:
            continue

        key = pdf_name_to_first_last(r["name"])
        swimmer = swimmer_index.get(key.lower()) if key else None
        if swimmer is None:
            # Only worth reporting when team_filter narrows things down first -
            # without it, most of a big meet's swimmers legitimately won't be
            # in your table, and that's not something to flag every time.
            if team_filter is not None:
                unmatched_names.add(r["name"])
            continue

        ev = r["event"]
        distance, stroke, course, relay = ev["distance"], ev["stroke"], ev["course"], ev.get("relay", False)

        if dry_run:
            # Read-only: never create events here, just check what's already imported.
            event = crud.get_event(db, distance, stroke, course, relay)
            meet_entry = event and crud.get_meet_entry(db, meet_id, swimmer.id, event.id)
            if meet_entry and crud.get_swim_time_by_meet_entry(db, meet_entry.id):
                stats["times_already_existed"] += 1
            else:
                stats["would_import"] += 1
            continue

        event = get_or_create_event(db, distance, stroke, course, relay, stats)

        meet_entry = crud.get_meet_entry(db, meet_id, swimmer.id, event.id)
        if meet_entry is None:
            meet_entry = crud.create_meet_entry(
                db, schemas.MeetEntryCreate(meet_id=meet_id, swimmer_id=swimmer.id, event_id=event.id)
            )
            stats["meet_entries_created"] += 1

        existing_time = crud.get_swim_time_by_meet_entry(db, meet_entry.id)
        if existing_time is not None:
            stats["times_already_existed"] += 1
            continue

        crud.create_swim_time(
            db,
            schemas.SwimTimeCreate(
                meet_entry_id=meet_entry.id,
                time_seconds=r["time_seconds"],
                notes=result_notes(r),
                dq=r.get("dq", False),
                dq_reason=r.get("dq_reason"),
                relay_leg=r.get("relay_leg"),
                split_seconds=r.get("split_seconds"),
            ),
        )
        stats["times_imported"] += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Import a Hy-Tek meet results PDF into swim_times.")
    parser.add_argument("pdf_path", help="Path to the results PDF")
    parser.add_argument(
        "--meet-id", type=int, required=True, help="ID of an existing Meet record to attach these results to"
    )
    parser.add_argument(
        "--team",
        default=None,
        help="Optional team abbreviation (e.g. WEST-MN) to additionally restrict matching to. "
        "By default, no team filter is applied - any result whose name matches an existing "
        "row in your swimmers table is imported, regardless of team.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and match only - don't write to the database")
    args = parser.parse_args()

    print(f"Parsing {args.pdf_path} ...")
    results, skip_counts = parse_pdf(args.pdf_path)
    dqs = sum(1 for r in results if r.get("dq"))
    relays = sum(1 for r in results if r["event"].get("relay"))
    print(f"Parsed {len(results)} results across all teams ({dqs} DQs, {relays} relay swims).")
    print(
        f"Skipped: {skip_counts['unsupported_event']} rows in Time Trial/unrecognized events, "
        f"{skip_counts['no_show_or_scratch']} no-show/scratch rows, "
        f"{skip_counts['unparsed_row']} unparsed rows."
    )

    if args.team is not None:
        team_results = [r for r in results if r["team"] == args.team]
        print(f"\n{len(team_results)} results found for team '{args.team}'.")

    stats = new_stats()
    unmatched_names = set()

    db = SessionLocal()
    try:
        import_results(db, results, args.meet_id, args.team, stats, unmatched_names, args.dry_run)
    finally:
        db.close()

    print()
    if args.dry_run:
        print(
            f"DRY RUN - would import {stats['would_import']} times, "
            f"{stats['times_already_existed']} already imported (no database changes made)."
        )
    else:
        print(f"New events auto-created: {stats['events_created']}")
        print(f"New meet entries created: {stats['meet_entries_created']}")
        print(f"Swim times imported: {stats['times_imported']}")
        print(f"Swim times already existed (skipped): {stats['times_already_existed']}")

    if unmatched_names:
        print(f"\n{len(unmatched_names)} swimmer name(s) in the results didn't match anyone in your swimmers table:")
        for n in sorted(unmatched_names):
            print(f"  - {n}  (would match as: {pdf_name_to_first_last(n)!r})")
        print("Add these swimmers via POST /swimmers/ and re-run to pick them up.")


if __name__ == "__main__":
    main()
