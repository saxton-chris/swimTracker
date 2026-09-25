"""Unit tests for the frontend's helpers (app/static/*.js), run in a real browser.

The frontend is ES modules, which don't create globals. The `js` fixture
imports the modules under test and copies their exports onto `window`, so
page.evaluate() can call them by name. A module is loaded once per page, so
`state` here is the same object the app itself uses.
"""

import pytest
from sqlalchemy.orm import sessionmaker

from conftest import make_test_engine, serve_db
from main import app

pytestmark = pytest.mark.ui

TESTED_MODULES = [
    "format.js",
    "api.js",
    "dom.js",
    "store.js",
    "standards-data.js",
    "progress-chart.js",
    "views/import.js",
]


@pytest.fixture(scope="module")
def js(browser, live_server, tmp_path_factory):
    """One loaded copy of the app (empty DB) shared by every test in this module."""
    engine = make_test_engine(tmp_path_factory.mktemp("js") / "js.db")
    serve_db(sessionmaker(bind=engine))
    context = browser.new_context(base_url=live_server, locale="en-US", timezone_id="America/Chicago")
    page = context.new_page()
    page.goto("/", wait_until="networkidle")
    page.evaluate(
        """async (modules) => {
            for (const m of modules) Object.assign(window, await import(`/static/${m}`));
        }""",
        TESTED_MODULES,
    )
    app.dependency_overrides.clear()  # page is loaded; the helpers below never hit the API
    yield page
    context.close()
    engine.dispose()


def call(js, fn, *args):
    """Call `fn(*args)` (a module export, see the `js` fixture); returns {"ok": value} or {"err": message}."""
    return js.evaluate(
        f"(args) => {{ try {{ return {{ ok: {fn}(...args) }}; }} catch (e) {{ return {{ err: e.message }}; }} }}",
        list(args),
    )


# --- formatTime --------------------------------------------------------------


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (32.4, "32.40"),
        (0.5, "0.50"),
        (59.99, "59.99"),
        (60, "1:00.00"),
        (62.45, "1:02.45"),
        (59.999, "1:00.00"),  # rounding to hundredths carries into the minute
        (605.1, "10:05.10"),
        (1000.07, "16:40.07"),
    ],
)
def test_format_time(js, seconds, expected):
    assert call(js, "formatTime", seconds) == {"ok": expected}


# --- parseTime ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("32.45", 32.45),
        (" 1:02.45 ", 62.45),
        ("2:45.3", 165.3),
        ("58", 58),
        ("0:59.99", 59.99),
        ("1:02.456", 62.46),  # rounded to hundredths
        ("16:40.07", 1000.07),
    ],
)
def test_parse_time_valid(js, text, expected):
    assert call(js, "parseTime", text) == {"ok": expected}


@pytest.mark.parametrize("text", ["", "   "])
def test_parse_time_blank_is_null(js, text):
    assert call(js, "parseTime", text) == {"ok": None}


@pytest.mark.parametrize(
    "text, message",
    [
        ("abc", "isn't a valid time"),
        ("-5", "isn't a valid time"),
        ("1.2.3", "isn't a valid time"),
        ("1:2:3", "isn't a valid time"),
        ("1:", "isn't a valid time"),
        ("1:75.00", "seconds must be under 60"),
        ("1:60", "seconds must be under 60"),
        ("0", "greater than zero"),
        ("0:00.00", "greater than zero"),
    ],
)
def test_parse_time_invalid(js, text, message):
    result = call(js, "parseTime", text)
    assert message in result["err"]


@pytest.mark.parametrize("seconds", [0.01, 25.5, 59.99, 60, 62.45, 165.3, 1000.07])
def test_parse_format_round_trip(js, seconds):
    formatted = call(js, "formatTime", seconds)["ok"]
    assert call(js, "parseTime", formatted) == {"ok": seconds}


# --- formatDate / ageOn ------------------------------------------------------


@pytest.mark.parametrize(
    "iso, expected",
    [
        ("2026-01-10", "Jan 10, 2026"),  # not Jan 9: parsed as a local date, not UTC midnight
        ("2026-12-31", "Dec 31, 2026"),
        ("2024-02-29", "Feb 29, 2024"),
    ],
)
def test_format_date(js, iso, expected):
    assert call(js, "formatDate", iso) == {"ok": expected}


@pytest.mark.parametrize(
    "start, end, expected",
    [
        ("2026-01-10", None, "Jan 10, 2026"),
        ("2026-01-10", "2026-01-10", "Jan 10, 2026"),  # same-day end reads as one day
        ("2026-01-09", "2026-01-11", "Jan 9 – 11, 2026"),
        ("2026-01-30", "2026-02-01", "Jan 30 – Feb 1, 2026"),
        ("2025-12-30", "2026-01-01", "Dec 30, 2025 – Jan 1, 2026"),
    ],
)
def test_format_meet_dates(js, start, end, expected):
    text = js.evaluate("([date, end_date]) => formatMeetDates({ date, end_date })", [start, end])
    # Intl.formatRange uses thin/narrow no-break spaces around the dash
    assert text.replace(" ", " ").replace(" ", " ") == expected


@pytest.mark.parametrize(
    "on, expected",
    [
        # months are 0-based in JS: (2026, 4, 1) is May 1
        ((2026, 3, 30), 11),  # day before 12th birthday
        ((2026, 4, 1), 12),  # birthday
        ((2026, 4, 2), 12),
        ((2026, 0, 1), 11),
        ((2026, 11, 31), 12),
    ],
)
def test_age_on(js, on, expected):
    age = js.evaluate("([y, m, d]) => ageOn('2014-05-01', new Date(y, m, d))", list(on))
    assert age == expected


# --- errorMessage ------------------------------------------------------------


def _error_message(js, data, status=400, status_text="Bad Request"):
    return js.evaluate(
        "([data, status, statusText]) => errorMessage(data, { status, statusText })",
        [data, status, status_text],
    )


def test_error_message_string_detail(js):
    assert _error_message(js, {"detail": "Meet 3 not found"}) == "Meet 3 not found"


def test_error_message_validation_list(js):
    data = {
        "detail": [
            {"loc": ["body", "name"], "msg": "Field required"},
            {"loc": ["body", "time_seconds"], "msg": "Input should be greater than 0"},
        ]
    }
    assert _error_message(js, data) == "name: Field required; time_seconds: Input should be greater than 0"


@pytest.mark.parametrize("data", [None, {}, {"detail": 5}])
def test_error_message_falls_back_to_status(js, data):
    assert _error_message(js, data, 500, "Internal Server Error") == "500 Internal Server Error"


# --- cascadeWarning ----------------------------------------------------------


@pytest.mark.parametrize(
    "entry_ids, timed_ids, expected",
    [
        ([], [], ""),
        ([1], [], "\n\nThis will also delete 1 meet entry."),
        ([1], [1], "\n\nThis will also delete 1 meet entry and 1 result."),
        ([1, 2], [2], "\n\nThis will also delete 2 meet entries and 1 result."),
        (
            [1, 2, 3],
            [1, 2, 3, 99],
            "\n\nThis will also delete 3 meet entries and 3 results.",
        ),  # 99: another entry's time
    ],
)
def test_cascade_warning(js, entry_ids, timed_ids, expected):
    result = js.evaluate(
        """([entryIds, timedIds]) => {
            const saved = state.times;
            state.times = timedIds.map((id, i) => ({ id: i + 1, meet_entry_id: id }));
            try { return cascadeWarning(entryIds.map((id) => ({ id }))); }
            finally { state.times = saved; }
        }""",
        [entry_ids, timed_ids],
    )
    assert result == expected


# --- DOM helpers -------------------------------------------------------------


def test_el_sets_text_not_html(js):
    html = js.evaluate("() => el('td', { textContent: '<b>x</b>' }).innerHTML")
    assert html == "&lt;b&gt;x&lt;/b&gt;"


def test_el_class_children_and_listeners(js):
    result = js.evaluate("""() => {
        let clicks = 0;
        const node = el('div', { class: 'a b', onclick: () => clicks++ }, 'text', null, el('span'));
        node.click();
        return [node.className, node.childNodes.length, clicks];
    }""")
    assert result == ["a b", 2, 1]  # null child skipped


def test_fill_select_keeps_selection_when_still_present(js):
    result = js.evaluate("""() => {
        const s = document.createElement('select');
        fillSelect(s, [{ id: 1, n: 'A' }, { id: 2, n: 'B' }], (x) => x.n, { blank: 'All' });
        s.value = '2';
        fillSelect(s, [{ id: 2, n: 'B' }, { id: 3, n: 'C' }], (x) => x.n, { blank: 'All' });
        const kept = s.value;
        fillSelect(s, [{ id: 3, n: 'C' }], (x) => x.n, { blank: 'All' });
        return [kept, s.value, [...s.options].map((o) => o.textContent)];
    }""")
    assert result == ["2", "", ["All", "C"]]  # falls back to blank once the item is gone


# --- importSummary -----------------------------------------------------------


def summary(parsed=5, imported=0, created=0, existed=0):
    return {
        "results_parsed": parsed,
        "times_imported": imported,
        "meet_entries_created": created,
        "times_already_existed": existed,
        "events_created": 0,
        "skipped": {},
    }


@pytest.mark.parametrize(
    "reply, expected",
    [
        (summary(parsed=0), "No individual results found in that PDF."),
        (summary(), "No results in that PDF matched a swimmer on the Swimmers tab."),
        (summary(imported=1, created=1), "Imported 1 time (1 new entry)."),
        (summary(imported=3), "Imported 3 times."),
        (summary(imported=3, created=2, existed=1), "Imported 3 times (2 new entries). 1 result was already recorded."),
        (summary(existed=2), "2 results were already recorded."),
    ],
)
def test_import_summary(js, reply, expected):
    assert call(js, "importSummary", reply) == {"ok": expected}


# --- standards: age groups and standing ----------------------------------------


@pytest.mark.parametrize(
    "label, expected",
    [
        ("11-12", [11, 12]),
        ("10 & under", [0, 10]),
        ("8 & Under", [0, 8]),
        ("10 & Under/9-10", [0, 10]),
        ("15-16/17 & Over/Senior", [15, 99]),
        ("Open", None),
    ],
)
def test_age_range(js, label, expected):
    assert call(js, "ageRange", label) == {"ok": expected}


MN_GROUPS = ["8 & Under", "10 & Under/9-10", "11-12", "13-14", "15-16/17 & Over/Senior"]
USA_GROUPS = ["10 & under", "11-12", "13-14", "15-16", "17-18"]


@pytest.mark.parametrize(
    "groups, age, expected",
    [
        (MN_GROUPS, 8, "8 & Under"),  # also inside "10 & Under/9-10": the narrower group wins
        (MN_GROUPS, 9, "10 & Under/9-10"),
        (MN_GROUPS, 12, "11-12"),
        (MN_GROUPS, 19, "15-16/17 & Over/Senior"),
        (USA_GROUPS, 7, "10 & under"),
        (USA_GROUPS, 17, "17-18"),
        (USA_GROUPS, 19, None),  # past the oldest group
    ],
)
def test_age_group_for(js, groups, age, expected):
    assert call(js, "ageGroupFor", groups, age) == {"ok": expected}


TIERS = [{"name": "B", "rank": 1, "seconds": 35.19}, {"name": "BB", "rank": 2, "seconds": 32.59},
         {"name": "A", "rank": 3, "seconds": 30.09}]  # fmt: skip


@pytest.mark.parametrize(
    "seconds, achieved, next_name, to_next",
    [
        (36.0, None, "B", 0.81),  # not there yet
        (35.19, "B", "BB", 2.6),  # exactly on the cut counts
        (32.45, "BB", "A", 2.36),
        (29.5, "A", None, None),  # top standard
    ],
)
def test_standing_for(js, seconds, achieved, next_name, to_next):
    got = call(js, "standingFor", seconds, TIERS)["ok"]
    assert (got["achieved"] and got["achieved"]["name"]) == achieved
    assert (got["next"] and got["next"]["name"]) == next_name
    assert got["toNext"] == to_next


@pytest.mark.parametrize(
    "on, expected",
    [("2026-04-30", 11), ("2026-05-01", 12), ("2027-01-10", 12)],
)
def test_age_at_meet_date(js, on, expected):
    assert call(js, "ageAt", "2014-05-01", on) == {"ok": expected}


# --- progress chart helpers ----------------------------------------------------


@pytest.mark.parametrize(
    "lo, hi, expected",
    [
        (32.45, 36.16, ["32.00", "33.00", "34.00", "35.00", "36.00"]),
        (58.2, 61.9, ["58.00", "59.00", "1:00.00", "1:01.00", "1:02.00"]),
        (95.0, 185.0, ["1:30.00", "2:00.00", "2:30.00", "3:00.00"]),
    ],
)
def test_time_ticks(js, lo, hi, expected):
    ticks = call(js, "timeTicks", lo, hi)["ok"]
    assert ticks["labels"] == expected
    low, high = ticks["range"]
    assert low < lo and high > hi  # the data sits inside the drawn range


def test_time_ticks_single_result_gets_at_least_a_second(js):
    ticks = call(js, "timeTicks", 36.16, 36.16)["ok"]
    low, high = ticks["range"]
    assert high - low >= 1
    assert low < 36.16 < high
    assert "36.00" in ticks["labels"]
    assert 3 <= len(ticks["values"]) <= 7


def test_progress_points_skip_dqs_and_untimed_and_sort_by_date(js):
    result = js.evaluate(
        """() => {
            const saved = { ...state };
            Object.assign(state, {
                meets: [{ id: 1, name: "Late", date: "2026-03-01" }, { id: 2, name: "Early", date: "2025-10-01" },
                        { id: 3, name: "Mid", date: "2026-01-10" }, { id: 4, name: "No time", date: "2026-02-01" }],
                entries: [{ id: 10, meet_id: 1, swimmer_id: 7, event_id: 5 }, { id: 11, meet_id: 2, swimmer_id: 7, event_id: 5 },
                          { id: 12, meet_id: 3, swimmer_id: 7, event_id: 5 }, { id: 13, meet_id: 4, swimmer_id: 7, event_id: 5 },
                          { id: 14, meet_id: 1, swimmer_id: 8, event_id: 5 },   // another swimmer
                          { id: 15, meet_id: 1, swimmer_id: 7, event_id: 6 }],  // another event
                times: [{ meet_entry_id: 10, time_seconds: 31.0, dq: false }, { meet_entry_id: 11, time_seconds: 34.0, dq: false },
                        { meet_entry_id: 12, time_seconds: 29.0, dq: true }, { meet_entry_id: 14, time_seconds: 20.0, dq: false },
                        { meet_entry_id: 15, time_seconds: 20.0, dq: false }],
            });
            try {
                const { points, dqs } = progressPoints(7, 5);
                return { meets: points.map((p) => p.meet), dqs, summary: progressSummary(points, dqs) };
            } finally { Object.assign(state, saved); }
        }"""
    )
    assert result == {
        "meets": ["Early", "Late"],  # the DQ (Mid) and the untimed entry are left out
        "dqs": 1,
        "summary": "2 swims · best 31.00 at Late (Mar 1, 2026) · 1 DQ not shown",
    }
