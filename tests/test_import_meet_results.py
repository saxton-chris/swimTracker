import sys

import pytest

import crud
import import_meet_results as imr
import schemas
from conftest import FakePage, FakePDF, word
from models import Course, MeetEntry, Stroke, SwimTime


def text_row(text, top, x_offset=0):
    return [word(t, x_offset + 10 + i * 10, top) for i, t in enumerate(text.split())]


def result_row(top, place, name, age, team, *times, x_offset=0):
    """Hy-Tek result row laid out with realistic left-to-right x positions."""
    words = [word(place, x_offset + 10, top)]
    words += [word(t, x_offset + 30 + i * 20, top) for i, t in enumerate(name.split())]
    words += [word(age, x_offset + 120, top), word(team, x_offset + 140, top)]
    words += [word(t, x_offset + 200 + i * 40, top) for i, t in enumerate(times)]
    return words


def rows_of(*word_lists):
    return [{"top": ws[0]["top"], "words": ws} for ws in word_lists]


# --- pure helpers ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1:23.49", 83.49),
        ("43.23", 43.23),
        ("X1:05.10", 65.1),
        ("X29.50", 29.5),
        ("NT", None),
        ("123:00.00", None),
    ],
)
def test_parse_time(raw, expected):
    assert imr.parse_time(raw) == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize(
    "pdf_name, expected",
    [
        ("Barber, Adella F", "Adella Barber"),
        ("Barber,Adella", "Adella Barber"),
        ("  Van Dyke ,  Sam  ", "Sam Van Dyke"),
        ("No Comma", None),
    ],
)
def test_pdf_name_to_first_last(pdf_name, expected):
    assert imr.pdf_name_to_first_last(pdf_name) == expected


def test_cluster_rows():
    rows = imr.cluster_rows([word("b", 0, 12), word("a", 0, 10), word("c", 0, 30)])
    assert [[w["text"] for w in r["words"]] for r in rows] == [["a", "b"], ["c"]]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Event 1 Girls 11-12 50 SC Yard Freestyle", ("50", "SC", "Yard", "Freestyle", None, None)),
        ("Boys 13-14 100 LC Meter Individual Medley", ("100", "LC", "Meter", "Individual Medley", None, None)),
        ("Event 7 Mixed 10 & Under 200 SC Meter Freestyle Relay", ("200", "SC", "Meter", "Freestyle", " Relay", None)),
        ("Event 9 Women Open 50 SC Yard Butterfly Time Trial", ("50", "SC", "Yard", "Butterfly", None, " Time Trial")),
    ],
)
def test_event_re(text, expected):
    m = imr.EVENT_RE.match(text)
    assert m.group("distance", "course", "unit", "stroke", "relay", "timetrial") == expected


class TestParseResultRow:
    def test_full_row_uses_last_time(self):
        r = imr.parse_result_row(result_row(0, "1", "Barber, Adella F", "12", "WEST-MN", "30.00", "29.50", "20"))
        assert r == {
            "place": "1",
            "name": "Barber, Adella F",
            "age": 12,
            "team": "WEST-MN",
            "time_seconds": pytest.approx(29.5),
        }

    def test_word_order_does_not_matter(self):
        words = result_row(0, "3", "Doe, Jo", "9", "AB-MN", "X45.00")
        r = imr.parse_result_row(list(reversed(words)))
        assert r["name"] == "Doe, Jo" and r["time_seconds"] == pytest.approx(45.0)

    @pytest.mark.parametrize(
        "words",
        [
            [],
            text_row("Barber, Adella 12 WEST-MN 30.00", 0),  # no place
            text_row("1 WEST-MN 1:50.00", 0),  # relay team row
            text_row("1 Barber, Adella 30.00", 0),  # no team token
            text_row("2 Foo WEST-MN 30.00", 0),  # no age before team
            text_row("1 Barber, Adella 12 WEST-MN DQ", 0),  # no time
        ],
    )
    def test_rejects(self, words):
        assert imr.parse_result_row(words) is None


# --- process_column --------------------------------------------------------

EVENT_50FR_SCY = {"distance": 50, "stroke": Stroke.FR, "course": Course.SCY, "relay": False}
EVENT_200FRR_SCY = {"distance": 200, "stroke": Stroke.FR, "course": Course.SCY, "relay": True}


def left_column_rows():
    return rows_of(
        text_row("Event 1 Girls 11-12 50 SC Yard Freestyle", 10),
        text_row("Name Age Team Seed Finals", 20),
        result_row(30, "1", "Barber, Adella F", "12", "WEST-MN", "30.00", "29.50"),
        text_row("--- Smith, Jane 11 WEST-MN DQ 31.20", 40),
        text_row("False start", 45),  # the DQ's reason
        text_row("15.00 29.50", 50),  # splits line
        text_row("2 Foo WEST-MN 30.00", 60),  # numbered but malformed
        text_row("--- Roe, Kim 11 WEST-MN NS", 65),  # no-show: skipped
        text_row("Event 2 Girls 11-12 200 SC Yard Freestyle Relay", 70),
        text_row("Team Relay Finals Time", 75),
        text_row("1 WEST-MN A 1:50.00 40", 80),
        text_row("1) Moe, Ann 12 2) Smith, Jane 11", 85),
        text_row("3) Doe, Jo 12 4) Roe, Kim W11", 90),  # mixed-relay style age prefix
        text_row("27.00 28.00 27.50 27.50", 95),  # per-leg splits, add up to 1:50.00
        text_row("--- NORTH-MN A DQ 2:01.00", 100),
        text_row("Early take-off swimmer #2", 105),
        text_row("1) Lee, Ann 12 2) Poe, Liz 12", 110),
        text_row("3) Kay, Mo 11 4) Fay, Jo 11", 115),
        text_row("Event 3 Girls 11-12 100 SC Yard Freestyle Extra", 120),  # header-like, unparseable
        result_row(125, "3", "Doe, Jo", "12", "WEST-MN", "1:10.00"),
        text_row("Hy-Tek Meet Manager", 130),
    )


def test_process_column(capsys):
    skips, state = imr.new_skip_counts(), {"event": None}
    results = imr.process_column(left_column_rows(), skips, state)

    assert [(r["name"], r["dq"]) for r in results] == [("Barber, Adella F", False), ("Smith, Jane", True)]
    assert results[0]["event"] == EVENT_50FR_SCY
    dq = results[1]
    assert (dq["time_seconds"], dq["dq_reason"], dq["place"]) == (pytest.approx(31.2), "False start", None)
    assert skips == {"unsupported_event": 1, "no_show_or_scratch": 1, "unparsed_row": 1}
    assert "unrecognized event header" in capsys.readouterr().out

    west, north = state["relay_teams"]
    assert (west["team"], west["place"], west["time_seconds"], west["dq"]) == ("WEST-MN", "1", 110.0, False)
    assert west["swimmers"] == [(1, "Moe, Ann", 12), (2, "Smith, Jane", 11), (3, "Doe, Jo", 12), (4, "Roe, Kim", 11)]
    assert west["splits"] == [27.0, 28.0, 27.5, 27.5]
    assert west["event"] == EVENT_200FRR_SCY
    assert (north["dq"], north["dq_reason"], north["place"]) == (True, "Early take-off swimmer #2", None)


@pytest.mark.parametrize(
    "header",
    [
        "Event 4 Boys 13-14 50 SC Yard Butterfly Time Trial",
        "Event 5 Boys 13-14 200 SC Meter Medley",  # "Medley" alone is only a relay stroke
        "Event 6 Boys 13-14 200 SC Meter Backstroke Relay",  # relays are Free or Medley
    ],
)
def test_process_column_skips_unsupported_blocks(header):
    skips = imr.new_skip_counts()
    rows = rows_of(text_row(header, 10), result_row(20, "1", "Lee, Sam", "13", "WEST-MN", "30.00"))
    assert imr.process_column(rows, skips) == []
    assert skips["unsupported_event"] == 1


def test_process_column_unknown_course_is_skipped_with_warning(capsys):
    skips = imr.new_skip_counts()
    rows = rows_of(
        text_row("Event 1 Girls 11-12 50 SC Yard Freestyle", 10),
        result_row(20, "1", "Barber, Adella", "12", "WEST-MN", "30.00"),
        text_row("Event 2 Girls 11-12 100 LC Yard Freestyle", 30),
        result_row(40, "1", "Lee, Sam", "12", "WEST-MN", "1:05.00"),
    )
    results = imr.process_column(rows, skips)
    # the LC Yard block's row isn't mis-attributed to the previous 50 SCY event
    assert [r["name"] for r in results] == ["Barber, Adella"]
    assert "unrecognized event header" in capsys.readouterr().out


def test_process_column_state_carries_event_into_next_column():
    """An event's header at the bottom of one column; its results continue at
    the top of the next column with no repeated header."""
    skips, state = imr.new_skip_counts(), {"event": None}
    first = rows_of(
        text_row("Boys 9-10 50 LC Meter Freestyle", 10),
        result_row(20, "1", "Gallant, Seb M", "10", "TUNA-MN", "32.64"),
    )
    second = rows_of(
        text_row("HY-TEK's MEET MANAGER 8.0 - Page 16", 5),  # page furniture, ignored
        result_row(10, "2", "Saxton, Alistair B", "10", "WEST-MN", "36.16", "CH"),
    )
    assert len(imr.process_column(first, skips, state)) == 1
    [carried] = imr.process_column(second, skips, state)
    assert carried["name"] == "Saxton, Alistair B"
    assert carried["time_seconds"] == pytest.approx(36.16)
    assert carried["event"] == {"distance": 50, "stroke": Stroke.FR, "course": Course.LCM, "relay": False}
    assert skips == imr.new_skip_counts()  # nothing miscounted as a skip


def test_process_column_without_state_starts_fresh():
    skips = imr.new_skip_counts()
    rows = rows_of(result_row(10, "2", "Saxton, Alistair B", "10", "WEST-MN", "36.16"))
    assert imr.process_column(rows, skips) == []
    assert skips["unsupported_event"] == 1


def test_relay_continues_into_next_column():
    """A relay team's row at a column's bottom; its swimmers and splits at the top of the next."""
    skips, state = imr.new_skip_counts(), {"event": None}
    imr.process_column(
        rows_of(text_row("Girls 9-10 200 LC Meter Medley Relay", 10), text_row("2 EDI-MN A 3:10.00 34", 700)),
        skips,
        state,
    )
    imr.process_column(
        rows_of(
            text_row("1) Aa, Bo 10 2) Cc, Di 10", 10),
            text_row("3) Ee, Fi 9 4) Gg, Hu 10", 20),
            text_row("50.00 45.00 50.00 45.00", 30),
        ),
        skips,
        state,
    )
    [team] = state["relay_teams"]
    assert team["event"] == {"distance": 200, "stroke": Stroke.IM, "course": Course.LCM, "relay": True}
    assert [s[1] for s in team["swimmers"]] == ["Aa, Bo", "Cc, Di", "Ee, Fi", "Gg, Hu"]
    assert team["splits"] == [50.0, 45.0, 50.0, 45.0]


def test_relay_no_show_is_skipped():
    skips, state = imr.new_skip_counts(), {"event": None}
    rows = rows_of(
        text_row("Girls 9-10 200 LC Meter Freestyle Relay", 10),
        text_row("--- EDI-MN A NS", 20),
        text_row("1) Aa, Bo 10 2) Cc, Di 10", 30),  # belongs to the no-show team: not attached anywhere
    )
    imr.process_column(rows, skips, state)
    assert state["relay_teams"] == []
    assert skips["no_show_or_scratch"] == 1


@pytest.mark.parametrize(
    "next_row, reason",
    [
        ("Scissors kick", "Scissors kick"),
        ("41.34 49.19", None),  # a splits line
        ("--- Doe, Jo 10 WEST-MN DQ 42.25", None),  # the next DQ
        ("Girls 9-10 100 LC Meter Butterfly", None),  # the next event
        ("Rochester Aquatic Center - MN - Site License", None),  # page furniture
    ],
)
def test_dq_reason_is_only_the_next_descriptive_row(next_row, reason):
    rows = rows_of(
        text_row("Girls 9-10 50 LC Meter Backstroke", 10),
        text_row("--- Zeuli, Ella C 10 RSC-MN DQ 1:02.97", 20),
        text_row(next_row, 30),
    )
    results = imr.process_column(rows, imr.new_skip_counts())
    assert results[0]["dq_reason"] == reason


def test_dq_reason_is_not_taken_from_the_next_column():
    """A DQ at a column's bottom: the next column's first row is page furniture, not its reason."""
    skips, state = imr.new_skip_counts(), {"event": None}
    [dq] = imr.process_column(
        rows_of(text_row("Girls 9-10 50 LC Meter Backstroke", 10), text_row("--- Zeuli, Ella C 10 RSC-MN DQ", 700)),
        skips,
        state,
    )
    imr.process_column(rows_of(text_row("MN LC 10&U State", 5)), skips, state)
    assert dq["dq_reason"] is None


@pytest.mark.parametrize(
    "header, expected_event",
    [
        (
            "(Boys 9-10 100 LC Meter Backstroke)",
            {"distance": 100, "stroke": Stroke.BK, "course": Course.LCM, "relay": False},
        ),
        ("(Boys 8 & Under 50 LC Meter Freestyle Time Trial)", None),
    ],
)
def test_process_column_parenthesized_continuation_header(header, expected_event):
    """Page-top '(Event ...)' continuation headers set the event, overriding stale state."""
    stale = {"distance": 50, "stroke": Stroke.FR, "course": Course.SCY, "relay": False}
    skips, state = imr.new_skip_counts(), {"event": stale}
    results = imr.process_column(
        rows_of(
            text_row(header, 10),
            result_row(20, "5", "Doe, Jo", "10", "WEST-MN", "1:30.00"),
        ),
        skips,
        state,
    )
    assert state["event"] == expected_event
    assert [r["event"] for r in results] == ([expected_event] if expected_event else [])


# --- unplaced rows, relay rows, splits ----------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("--- Breczinski, Simon 10 BASS-MN DQ 42.96", ("Breczinski, Simon", 10, "BASS-MN", 42.96, "DQ", False)),
        ("--- Perfect, Hunter 10 RFSC-MN DQ DQ", ("Perfect, Hunter", 10, "RFSC-MN", None, "DQ", False)),
        ("--- McGovern, Mavis M 7 HURR-MN X59.34", ("McGovern, Mavis M", 7, "HURR-MN", 59.34, None, True)),
        ("--- Acosta, Jojo R 8 PRNH-MN SCR", ("Acosta, Jojo R", 8, "PRNH-MN", None, "SCR", False)),
    ],
)
def test_parse_unplaced_row(text, expected):
    r = imr.parse_unplaced_row(text_row(text, 0))
    assert (r["name"], r["age"], r["team"], r["time_seconds"], r["mark"], r["exhibition"]) == expected


@pytest.mark.parametrize("text", ["--- WEST-MN DQ", "1 Barber, Adella 12 WEST-MN 30.00", "--- Doe, Jo WEST-MN DQ"])
def test_parse_unplaced_row_rejects(text):
    assert imr.parse_unplaced_row(text_row(text, 0)) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1 WEST-MN A 2:39.11 40", ("1", "WEST-MN", 159.11, False, False)),
        ("23 WEST-MN A 3:05.20 3:04.99", ("23", "WEST-MN", 184.99, False, False)),  # seed, then finals
        ("--- NOR-MN A DQ 4:28.60", (None, "NOR-MN", 268.6, True, False)),
        ("--- EDI-MN B SCR", (None, "EDI-MN", None, False, True)),
    ],
)
def test_parse_relay_team_row(text, expected):
    t = imr.parse_relay_team_row(text_row(text, 0))
    assert (t["place"], t["team"], t["time_seconds"], t["dq"], t["no_show"]) == expected


@pytest.mark.parametrize("text", ["1 Barber, Adella 12 WEST-MN 30.00", "1 WEST-MN 1:50.00", "1) Aa, Bo 10"])
def test_parse_relay_team_row_rejects(text):
    assert imr.parse_relay_team_row(text_row(text, 0)) is None


@pytest.mark.parametrize(
    "splits, team_time, expected",
    [
        ([42.17, 58.24, 42.64, 41.94], 184.99, [42.17, 58.24, 42.64, 41.94]),  # per-leg
        ([37.37, 76.76, 121.68, 159.11], 159.11, [37.37, 39.39, 44.92, 37.43]),  # cumulative
        ([47.53, 48.91, 85.73], 182.17, None),  # 3 values: can't tell which legs
        ([40.0, 40.0, 40.0, 40.0], 170.0, None),  # neither adds up: don't guess
        ([40.0, 40.0, 40.0, 40.0], None, None),  # relay DQ without a time
    ],
)
def test_relay_leg_splits(splits, team_time, expected):
    got = imr.relay_leg_splits(splits, team_time)
    assert got == (pytest.approx(expected) if expected else None)


def test_relay_results_one_per_swimmer():
    team = imr.parse_relay_team_row(text_row("5 WEST-MN A 3:04.99", 0))
    team.update(
        event=EVENT_200FRR_SCY,
        swimmers=[(1, "Aa, Bo", 10), (2, "Cc, Di", 10), (3, "Ee, Fi", 10), (4, "Saxton, Alistair B", 10)],
        splits=[42.17, 58.24, 42.64, 41.94],
    )
    results = imr.relay_results(team)
    assert len(results) == 4
    mine = results[3]
    assert (mine["name"], mine["relay_leg"], mine["split_seconds"]) == ("Saxton, Alistair B", 4, 41.94)
    assert (mine["time_seconds"], mine["place"], mine["team"], mine["dq"]) == (184.99, "5", "WEST-MN", False)


# --- parse_pdf -------------------------------------------------------------


def results_pages():
    right = text_row("Event 4 Boys 13-14 100 LC Meter Butterfly", 10, x_offset=300)
    right += result_row(20, "1", "Lee, Sam", "13", "NORTH-MN", "1:05.10", x_offset=300)
    left = [w for row in left_column_rows() for w in row["words"]]
    return [FakePage(left + right)]


def test_parse_pdf_splits_columns(fake_pdfplumber):
    fake_pdfplumber(imr, {"results.pdf": results_pages()})
    results, skips = imr.parse_pdf("results.pdf")

    individual = [(r["name"], r["team"], r["dq"]) for r in results if not r["event"]["relay"]]
    assert individual == [
        ("Barber, Adella F", "WEST-MN", False),
        ("Smith, Jane", "WEST-MN", True),
        ("Lee, Sam", "NORTH-MN", False),
    ]
    assert results[2]["event"] == {"distance": 100, "stroke": Stroke.FL, "course": Course.LCM, "relay": False}
    assert results[2]["time_seconds"] == pytest.approx(65.1)

    relay = [(r["name"], r["relay_leg"], r["split_seconds"], r["dq"]) for r in results if r["event"]["relay"]]
    assert relay[:4] == [("Moe, Ann", 1, 27.0, False), ("Smith, Jane", 2, 28.0, False),
                         ("Doe, Jo", 3, 27.5, False), ("Roe, Kim", 4, 27.5, False)]  # fmt: skip
    assert [(name, dq) for name, _, _, dq in relay[4:]] == [
        ("Lee, Ann", True),
        ("Poe, Liz", True),
        ("Kay, Mo", True),
        ("Fay, Jo", True),
    ]
    assert skips == {"unsupported_event": 1, "no_show_or_scratch": 1, "unparsed_row": 1}


def test_parse_pdf_event_continues_across_columns_and_pages(fake_pdfplumber):
    page1_left = text_row("Boys 9-10 50 LC Meter Freestyle", 700)  # header at column bottom
    page1_right = result_row(80, "1", "Du, Winston E", "10", "AQJT-MN", "33.04", x_offset=300)
    page2_left = result_row(80, "2", "Saxton, Alistair B", "10", "WEST-MN", "36.16", "CH")
    page2_left += text_row("Boys 9-10 100 LC Meter Freestyle", 200)
    page2_left += result_row(220, "1", "Dennis, Brody", "10", "FOXJ-MN", "1:13.53")
    fake_pdfplumber(imr, {"results.pdf": [FakePage(page1_left + page1_right), FakePage(page2_left)]})

    results, skips = imr.parse_pdf("results.pdf")
    assert [(r["name"], r["event"]["distance"]) for r in results] == [
        ("Du, Winston E", 50),
        ("Saxton, Alistair B", 50),
        ("Dennis, Brody", 100),
    ]
    assert skips == imr.new_skip_counts()


# --- import_results --------------------------------------------------------


def result(
    name="Barber, Adella F", team="WEST-MN", time=29.5, distance=50, stroke=Stroke.FR, course=Course.SCY, place="1"
):
    return {
        "place": place,
        "name": name,
        "age": 12,
        "team": team,
        "time_seconds": time,
        "event": {"distance": distance, "stroke": stroke, "course": course},
    }


new_stats = imr.new_stats


def run_import(db, results, meet_id, team=None, dry_run=False):
    stats, unmatched = new_stats(), set()
    imr.import_results(db, results, meet_id, team, stats, unmatched, dry_run)
    return stats, unmatched


def test_import_results_records_a_dq_with_its_reason(db, swimmer, meet):
    dq = {**result(time=None, place=None), "dq": True, "dq_reason": "False start"}
    stats, _ = run_import(db, [dq], meet.id)
    assert stats["times_imported"] == 1
    st = db.query(SwimTime).one()
    assert (st.dq, st.dq_reason, st.time_seconds) == (True, "False start", None)
    assert st.notes == "Imported from meet results PDF"  # a DQ has no place


def test_import_results_records_a_relay_leg(db, swimmer, meet):
    relay = {
        **result(time=184.99, distance=200, stroke=Stroke.IM, course=Course.LCM, place="23"),
        "relay_leg": 4,
        "split_seconds": 41.94,
    }
    relay["event"]["relay"] = True
    stats, _ = run_import(db, [relay, result()], meet.id)  # the relay plus an individual swim

    assert (stats["events_created"], stats["meet_entries_created"], stats["times_imported"]) == (2, 2, 2)
    st = db.query(SwimTime).join(MeetEntry).filter(MeetEntry.event.has(relay=True)).one()
    assert st.meet_entry.event.name == "200 MED-R LCM"
    assert (st.time_seconds, st.relay_leg, st.split_seconds, st.dq) == (184.99, 4, 41.94, False)


def test_import_results_exhibition_note(db, swimmer, meet):
    run_import(db, [{**result(place=None), "exhibition": True}], meet.id)
    assert db.query(SwimTime).one().notes == "Imported from meet results PDF, exhibition"


def test_import_results_requires_existing_meet(db, capsys):
    with pytest.raises(SystemExit):
        run_import(db, [result()], meet_id=999)
    assert "no meet exists with id=999" in capsys.readouterr().out


def test_import_results_creates_event_entry_and_time(db, swimmer, meet):
    stats, unmatched = run_import(db, [result(), result(name="Nobody, X"), result(name="No Comma")], meet.id)

    assert stats["events_created"] == 1
    assert stats["meet_entries_created"] == 1
    assert stats["times_imported"] == 1
    assert unmatched == set()  # without a team filter, unmatched names aren't reported

    st = db.query(SwimTime).one()
    assert st.time_seconds == pytest.approx(29.5)
    assert st.notes == "Imported from meet results PDF, place 1"
    assert st.meet_entry.swimmer_id == swimmer.id


def test_import_results_name_match_is_case_insensitive(db, swimmer, meet):
    stats, _ = run_import(db, [result(name="BARBER, ADELLA")], meet.id)
    assert stats["times_imported"] == 1


def test_import_results_is_idempotent(db, swimmer, meet):
    run_import(db, [result()], meet.id)
    stats, _ = run_import(db, [result()], meet.id)
    assert stats == {**new_stats(), "times_already_existed": 1}
    assert db.query(MeetEntry).count() == 1


def test_import_results_reuses_existing_entry(db, meet_entry, meet):
    stats, _ = run_import(db, [result()], meet.id)
    assert (stats["events_created"], stats["meet_entries_created"], stats["times_imported"]) == (0, 0, 1)


def test_import_results_team_filter(db, swimmer, meet):
    results = [result(team="OTHER-MN"), result(name="Ghost, Casper", team="WEST-MN")]
    stats, unmatched = run_import(db, results, meet.id, team="WEST-MN")
    assert stats["times_imported"] == 0
    assert unmatched == {"Ghost, Casper"}


def test_import_results_dry_run_writes_nothing(db, swimmer, meet):
    stats, _ = run_import(db, [result()], meet.id, dry_run=True)
    assert stats["would_import"] == 1
    assert crud.get_events(db) == []
    assert db.query(MeetEntry).count() == 0


def test_import_results_dry_run_event_exists_without_entry(db, swimmer, meet, swim_event):
    stats, _ = run_import(db, [result()], meet.id, dry_run=True)
    assert stats["would_import"] == 1


def test_import_results_dry_run_reports_already_imported(db, swimmer, meet):
    run_import(db, [result()], meet.id)
    stats, _ = run_import(db, [result()], meet.id, dry_run=True)
    assert (stats["would_import"], stats["times_already_existed"]) == (0, 1)


# --- main ------------------------------------------------------------------


@pytest.fixture
def run_main(db, session_factory, fake_pdfplumber, monkeypatch, capsys):
    fake_pdfplumber(imr, {"results.pdf": results_pages()})
    monkeypatch.setattr(imr, "SessionLocal", session_factory)

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["import_meet_results.py", "results.pdf", *args])
        imr.main()
        return capsys.readouterr().out

    return run


def test_main_imports(run_main, db, swimmer, meet):
    out = run_main("--meet-id", str(meet.id))
    assert "Parsed 11 results across all teams (5 DQs, 8 relay swims)" in out
    assert "Swim times imported: 1" in out
    assert db.query(SwimTime).count() == 1


def test_main_team_filter_reports_unmatched(run_main, db, meet):
    crud.create_swimmer(db, schemas.SwimmerCreate(name="Someone Else", birthdate="2012-01-01", gender="M"))
    out = run_main("--meet-id", str(meet.id), "--team", "WEST-MN")
    assert "6 results found for team 'WEST-MN'" in out  # Barber, Smith's DQ, the 4-swimmer relay
    assert "Barber, Adella F  (would match as: 'Adella Barber')" in out


def test_main_dry_run(run_main, db, swimmer, meet):
    out = run_main("--meet-id", str(meet.id), "--dry-run")
    assert "DRY RUN - would import 1 times" in out
    assert db.query(SwimTime).count() == 0


def test_main_requires_meet_id(run_main):
    with pytest.raises(SystemExit):
        run_main()


# --- POST /meets/{id}/import-results ---------------------------------------


@pytest.fixture
def upload(client, monkeypatch):
    """POSTs a PDF body to the import endpoint; pdfplumber sees results_pages()."""
    monkeypatch.setattr(imr.pdfplumber, "open", lambda f: FakePDF(results_pages()))

    def post(meet_id, body=b"%PDF-1.7 fake"):
        return client.post(
            f"/meets/{meet_id}/import-results", content=body, headers={"Content-Type": "application/pdf"}
        )

    return post


def test_import_endpoint_creates_entry_and_time(upload, db, swimmer, meet):
    r = upload(meet.id)
    assert r.status_code == 200
    body = r.json()
    assert body["results_parsed"] == 11  # incl. the DQ and 8 relay swims (none by our swimmers)
    assert (body["meet_entries_created"], body["times_imported"], body["times_already_existed"]) == (1, 1, 0)
    assert body["skipped"] == {"unsupported_event": 1, "no_show_or_scratch": 1, "unparsed_row": 1}

    st = db.query(SwimTime).one()
    assert st.meet_entry.meet_id == meet.id
    assert st.meet_entry.swimmer_id == swimmer.id


def test_import_endpoint_adds_time_to_existing_entry(upload, db, meet_entry, meet):
    body = upload(meet.id).json()
    assert (body["meet_entries_created"], body["times_imported"]) == (0, 1)
    assert db.query(MeetEntry).count() == 1
    assert db.query(SwimTime).one().meet_entry_id == meet_entry.id


def test_import_endpoint_is_idempotent(upload, db, swimmer, meet):
    upload(meet.id)
    body = upload(meet.id).json()
    assert (body["meet_entries_created"], body["times_imported"], body["times_already_existed"]) == (0, 0, 1)
    assert db.query(SwimTime).count() == 1


def test_import_endpoint_unknown_meet(upload):
    r = upload(999)
    assert r.status_code == 404


def test_import_endpoint_rejects_non_pdf(upload, meet):
    r = upload(meet.id, body=b"not a pdf")
    assert r.status_code == 400
    assert "isn't a PDF" in r.json()["detail"]


def test_import_endpoint_unreadable_pdf(upload, meet, monkeypatch):
    def broken(f):
        raise ValueError("bad xref")

    monkeypatch.setattr(imr.pdfplumber, "open", broken)
    r = upload(meet.id)
    assert r.status_code == 400
    assert "bad xref" in r.json()["detail"]
