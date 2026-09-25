"""End-to-end tests of the web frontend (app/static) in a headless browser.

Each test gets a fresh in-memory DB served by a live uvicorn instance (see the
`page` fixture in conftest). Data is seeded through crud before the page loads
and verified afterwards through the HTTP API, never the test's own session.
"""

from datetime import date
from types import SimpleNamespace

import pytest

import crud
import schemas
from conftest import make_test_engine

expect = pytest.importorskip("playwright.sync_api").expect

pytestmark = pytest.mark.ui


@pytest.fixture
def engine(tmp_path):
    """Overrides conftest's in-memory engine: the live server answers the page's
    parallel requests on several threads, so it needs a real (file) DB."""
    eng = make_test_engine(tmp_path / "ui.db")
    yield eng
    eng.dispose()


# --- helpers -----------------------------------------------------------------


def open_app(page, view="entries"):
    page.goto(f"/#{view}", wait_until="networkidle")


def api(page, path):
    return page.request.get(path).json()


def fill(page, form_id, **fields):
    for name, value in fields.items():
        field = page.locator(f"#{form_id} [name={name}]")
        if field.evaluate("e => e.tagName") == "SELECT":
            field.select_option(str(value))
        elif field.get_attribute("type") == "checkbox":
            field.set_checked(bool(value))
        else:
            field.fill(str(value))


def save(page, dialog_id, form_id, **fields):
    """Fill the dialog's form, click Save, and wait for it to close (all writes done)."""
    fill(page, form_id, **fields)
    page.locator(f"#{form_id} button[type=submit]").click()
    expect(page.locator(f"#{dialog_id}")).to_be_hidden()


def row(page, table, text):
    return page.locator(f"#{table}-body tr").filter(has_text=text)


def click_row_button(page, table, text, button):
    row(page, table, text).get_by_role("button", name=button, exact=True).click()


def toast(page):
    return page.locator("#toast")


@pytest.fixture
def seeded(db, swimmer, meet, swim_event, meet_entry):
    """Adella (timed 32.45, notes "PB") and Ben (no time) both swim 50 FR SCY at Winter Invite."""
    ben = crud.create_swimmer(db, schemas.SwimmerCreate(name="Ben Cho", birthdate=date(2012, 11, 20), gender="M"))
    ben_entry = crud.create_meet_entry(
        db, schemas.MeetEntryCreate(meet_id=meet.id, swimmer_id=ben.id, event_id=swim_event.id)
    )
    crud.create_swim_time(db, schemas.SwimTimeCreate(meet_entry_id=meet_entry.id, time_seconds=32.45, notes="PB"))
    return SimpleNamespace(
        adella_id=swimmer.id,
        ben_id=ben.id,
        meet_id=meet.id,
        event_id=swim_event.id,
        adella_entry_id=meet_entry.id,
        ben_entry_id=ben_entry.id,
    )


# --- rendering & navigation --------------------------------------------------


def test_renders_seeded_entries(page, seeded):
    open_app(page)
    expect(page.locator("#entries-body tr.entry")).to_have_count(2)
    # Both entries sit under a single heading row for their meet.
    expect(page.locator("#entries-body tr.meet-heading")).to_have_text(["Winter Invite Jan 10, 2026"])
    adella = row(page, "entries", "Adella Barber")
    for text in ("50 FR SCY", "32.45", "PB"):
        expect(adella).to_contain_text(text)
    expect(adella.locator(".clock")).to_have_text("32.45")  # scoreboard-style time readout
    expect(adella.get_by_role("button", name="Edit")).to_be_visible()
    ben = row(page, "entries", "Ben Cho")
    expect(ben).to_contain_text("—")
    expect(ben.get_by_role("button", name="Add time")).to_be_visible()


def test_swimmers_and_meets_tables(page, seeded):
    open_app(page, "swimmers")
    expect(row(page, "swimmers", "Adella Barber")).to_contain_text("May 1, 2014")
    expect(row(page, "swimmers", "Ben Cho")).to_contain_text("M")
    open_app(page, "meets")
    expect(row(page, "meets", "Winter Invite").locator("td.num")).to_have_text("2")  # entry count


def test_user_text_is_rendered_as_text_not_html(page, db):
    crud.create_swimmer(
        db,
        schemas.SwimmerCreate(
            name="<img src=x onerror=window.pwned=1>",
            birthdate=date(2014, 1, 1),
            gender="F",
            notes="<b>bold</b>",
        ),
    )
    open_app(page, "swimmers")
    expect(page.locator("#swimmers-body")).to_contain_text("<img src=x onerror=window.pwned=1>")
    expect(page.locator("#swimmers-body")).to_contain_text("<b>bold</b>")
    assert page.locator("#swimmers-body img, #swimmers-body b").count() == 0
    assert page.evaluate("window.pwned") is None


def test_empty_states(page):
    open_app(page)
    expect(page.locator("#entries-empty")).to_have_text("No meet entries yet.")
    page.get_by_role("tab", name="Swimmers").click()
    expect(page.locator("#swimmers-empty")).to_be_visible()
    page.get_by_role("tab", name="Meets").click()
    expect(page.locator("#meets-empty")).to_be_visible()


def test_tabs_follow_and_update_url_hash(page):
    open_app(page, "meets")
    expect(page.locator("#view-meets")).to_be_visible()
    expect(page.locator("#view-entries")).to_be_hidden()
    expect(page.get_by_role("tab", name="Meets")).to_have_attribute("aria-selected", "true")

    page.get_by_role("tab", name="Swimmers").click()
    expect(page.locator("#view-swimmers")).to_be_visible()
    assert page.url.endswith("#swimmers")

    page.goto("about:blank")  # force a real load; a hash-only change doesn't reload the app
    open_app(page, "bogus")  # unknown view falls back to entries
    expect(page.locator("#view-entries")).to_be_visible()
    assert page.url.endswith("#entries")


def test_load_failure_shows_error_toast(page):
    page.route("**/swimmers/", lambda route: route.fulfill(status=500, json={"detail": "db is down"}))
    open_app(page)
    expect(toast(page)).to_have_text("Couldn't load data: db is down")
    expect(toast(page)).to_have_class("toast error")


@pytest.mark.parametrize("view", ["entries", "swimmers", "meets"])
def test_table_cells_fill_their_rows(page, db, seeded, view):
    """Every cell in a row must end at the same height, or the row divider
    lines break (regression: the dialog's `.actions` rule once turned the
    table's td.actions into a flex box that didn't stretch to the row)."""
    crud.update_swim_time(db, 1, schemas.SwimTimeUpdate(notes="Imported from meet results PDF, place 25"))
    crud.update_swimmer(
        db, seeded.adella_id, schemas.SwimmerUpdate(notes="Long enough to wrap onto a second line in the notes column")
    )
    page.set_viewport_size({"width": 1100, "height": 800})
    open_app(page, view)
    bottoms = page.evaluate(f"""() => [...document.querySelectorAll('#{view}-body tr')].map(tr =>
        [...tr.children].filter(td => td.getClientRects().length)  // skip hidden cells (e.g. Standard)
            .map(td => Math.round(td.getBoundingClientRect().bottom)))""")
    assert bottoms and all(len(set(row)) == 1 for row in bottoms), bottoms


@pytest.mark.parametrize("view", ["entries", "swimmers", "meets"])
def test_no_horizontal_page_scroll_on_phone(page, seeded, view):
    page.set_viewport_size({"width": 375, "height": 800})
    open_app(page, view)
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0


# --- swimmers ----------------------------------------------------------------


def test_add_swimmer(page):
    open_app(page, "swimmers")
    page.get_by_role("button", name="+ Add swimmer").click()
    expect(page.locator("#swimmer-dialog h2")).to_have_text("Add swimmer")
    save(page, "swimmer-dialog", "swimmer-form", name="  Cara Diaz  ", birthdate="2015-03-04", gender="M", notes="  ")

    [cara] = api(page, "/swimmers/")
    assert cara == {"id": cara["id"], "name": "Cara Diaz", "birthdate": "2015-03-04", "gender": "M", "notes": None}
    expect(row(page, "swimmers", "Cara Diaz")).to_be_visible()
    expect(toast(page)).to_have_text("Swimmer added")


def test_required_fields_block_submit(page):
    open_app(page, "swimmers")
    page.get_by_role("button", name="+ Add swimmer").click()
    page.locator("#swimmer-form button[type=submit]").click()  # name/birthdate empty
    expect(page.locator("#swimmer-dialog")).to_be_visible()
    assert api(page, "/swimmers/") == []


def test_cancel_saves_nothing(page):
    open_app(page, "swimmers")
    page.get_by_role("button", name="+ Add swimmer").click()
    fill(page, "swimmer-form", name="Nope", birthdate="2015-01-01")
    page.locator("#swimmer-form .cancel").click()
    expect(page.locator("#swimmer-dialog")).to_be_hidden()
    assert api(page, "/swimmers/") == []


def test_edit_swimmer(page, db):
    crud.create_swimmer(
        db, schemas.SwimmerCreate(name="Ann Lee", birthdate=date(2013, 2, 3), gender="F", notes="likes fly")
    )
    open_app(page, "swimmers")
    click_row_button(page, "swimmers", "Ann Lee", "Edit")
    expect(page.locator("#swimmer-dialog h2")).to_have_text("Edit swimmer")
    expect(page.locator("#swimmer-form [name=birthdate]")).to_have_value("2013-02-03")
    expect(page.locator("#swimmer-form [name=notes]")).to_have_value("likes fly")

    save(page, "swimmer-dialog", "swimmer-form", name="Ann Lee-Park", notes="")
    [ann] = api(page, "/swimmers/")
    assert (ann["name"], ann["birthdate"], ann["notes"]) == ("Ann Lee-Park", "2013-02-03", None)
    expect(toast(page)).to_have_text("Swimmer updated")


def test_delete_swimmer_cascades_after_warning(page, seeded, confirms):
    open_app(page, "swimmers")
    click_row_button(page, "swimmers", "Adella Barber", "Delete")
    expect(toast(page)).to_have_text("Swimmer deleted")

    assert confirms.messages == ["Delete Adella Barber?\n\nThis will also delete 1 meet entry and 1 result."]
    assert [s["name"] for s in api(page, "/swimmers/")] == ["Ben Cho"]
    assert [e["id"] for e in api(page, "/meet_entries/")] == [seeded.ben_entry_id]
    assert api(page, "/swim_times/") == []
    expect(row(page, "swimmers", "Adella Barber")).to_have_count(0)


def test_dismissed_confirm_deletes_nothing(page, seeded, confirms):
    confirms.accept = False
    open_app(page, "swimmers")
    click_row_button(page, "swimmers", "Adella Barber", "Delete")
    page.wait_for_timeout(300)
    assert len(confirms.messages) == 1
    assert len(api(page, "/swimmers/")) == 2
    assert len(api(page, "/swim_times/")) == 1


def test_delete_of_already_deleted_row_shows_error_and_refreshes(page, seeded):
    open_app(page, "swimmers")
    page.request.delete(f"/swimmers/{seeded.ben_id}")  # removed behind the page's back
    click_row_button(page, "swimmers", "Ben Cho", "Delete")
    expect(toast(page)).to_have_text(f"Swimmer {seeded.ben_id} not found")
    expect(toast(page)).to_have_class("toast error")
    expect(row(page, "swimmers", "Ben Cho")).to_have_count(0)


# --- meets -------------------------------------------------------------------


def test_add_and_edit_meet(page):
    open_app(page, "meets")
    page.get_by_role("button", name="+ Add meet").click()
    save(page, "meet-dialog", "meet-form", name="Spring Champs", date="2026-03-01", location="")
    [meet] = api(page, "/meets/")
    assert (meet["name"], meet["date"], meet["location"]) == ("Spring Champs", "2026-03-01", None)
    expect(row(page, "meets", "Spring Champs")).to_contain_text("Mar 1, 2026")

    click_row_button(page, "meets", "Spring Champs", "Edit")
    expect(page.locator("#meet-form [name=date]")).to_have_value("2026-03-01")
    save(page, "meet-dialog", "meet-form", location="Edina")
    assert api(page, "/meets/")[0]["location"] == "Edina"
    expect(row(page, "meets", "Spring Champs")).to_contain_text("Edina")


def normalize_spaces(text):
    return text.replace(" ", " ").replace(" ", " ")


def test_add_and_edit_multi_day_meet(page):
    open_app(page, "meets")
    page.get_by_role("button", name="+ Add meet").click()
    save(page, "meet-dialog", "meet-form", name="State Champs", date="2026-03-06", end_date="2026-03-08")
    [meet] = api(page, "/meets/")
    assert (meet["date"], meet["end_date"]) == ("2026-03-06", "2026-03-08")
    assert normalize_spaces(row(page, "meets", "State Champs").locator("td").first.inner_text()) == "Mar 6 – 8, 2026"

    click_row_button(page, "meets", "State Champs", "Edit")
    expect(page.locator("#meet-form [name=end_date]")).to_have_value("2026-03-08")
    save(page, "meet-dialog", "meet-form", end_date="")  # now a one-day meet
    assert api(page, "/meets/")[0]["end_date"] is None
    expect(row(page, "meets", "State Champs").locator("td").first).to_have_text("Mar 6, 2026")


def test_meet_end_before_start_shows_error_and_saves_nothing(page):
    open_app(page, "meets")
    page.get_by_role("button", name="+ Add meet").click()
    fill(page, "meet-form", name="Backwards", date="2026-03-08", end_date="2026-03-06")
    page.locator("#meet-form button[type=submit]").click()
    expect(page.locator("#meet-form .form-error")).to_have_text("End date must be on or after the start date.")
    expect(page.locator("#meet-dialog")).to_be_visible()
    assert api(page, "/meets/") == []


def test_entries_show_multi_day_meet_range(page, db, meet_entry, meet):
    crud.update_meet(db, meet.id, schemas.MeetUpdate(end_date=date(2026, 1, 11), location="Edina"))
    open_app(page)
    dates = page.locator("#entries-body tr.meet-heading .meet-dates")
    assert normalize_spaces(dates.inner_text()) == "Jan 10 – 11, 2026"
    expect(page.locator("#entries-body tr.meet-heading .meet-location")).to_have_text("Edina")


def test_meets_sorted_oldest_first_by_start_date(page, db, swimmer):
    # "Mid" starts before "Late" but ends after it: the start date decides.
    for name, start, end in [
        ("New", date(2026, 6, 1), None),
        ("Late", date(2025, 9, 5), None),
        ("Old", date(2025, 1, 1), None),
        ("Mid", date(2025, 9, 1), date(2025, 9, 10)),
    ]:
        crud.create_meet(db, schemas.MeetCreate(name=name, date=start, end_date=end))
    expected = ["Old", "Mid", "Late", "New"]

    open_app(page, "meets")
    expect(page.locator("#meets-body tr td:nth-child(2)")).to_have_text(expected)

    page.get_by_role("tab", name="Entries & Results").click()
    options = page.locator("#filter-meet option").all_inner_texts()[1:]  # skip "All meets"
    assert [o.split(" (")[0] for o in options] == expected

    # New entries and imports still default to the most recent meet.
    page.get_by_role("button", name="+ Add entry").click()
    expect(page.locator("#entry-form [name=meet_id] option:checked")).to_contain_text("New")
    page.locator("#entry-form .cancel").click()
    page.get_by_role("button", name="Import results").click()
    expect(page.locator("#import-form [name=meet_id] option:checked")).to_contain_text("New")


def test_delete_meet_cascades_after_warning(page, seeded, confirms):
    open_app(page, "meets")
    click_row_button(page, "meets", "Winter Invite", "Delete")
    expect(toast(page)).to_have_text("Meet deleted")
    assert confirms.messages == ['Delete meet "Winter Invite"?\n\nThis will also delete 2 meet entries and 1 result.']
    assert api(page, "/meets/") == []
    assert api(page, "/meet_entries/") == []
    assert api(page, "/swim_times/") == []
    assert len(api(page, "/swimmers/")) == 2


def test_delete_meet_without_entries_has_no_cascade_warning(page, meet, confirms):
    open_app(page, "meets")
    click_row_button(page, "meets", "Winter Invite", "Delete")
    expect(toast(page)).to_have_text("Meet deleted")
    assert confirms.messages == ['Delete meet "Winter Invite"?']


# --- entries: filtering ------------------------------------------------------


@pytest.fixture
def two_meets(db, seeded):
    """Adds a second meet where only Ben swims."""
    other = crud.create_meet(db, schemas.MeetCreate(name="Spring Champs", date=date(2026, 3, 1)))
    crud.create_meet_entry(
        db,
        schemas.MeetEntryCreate(
            meet_id=other.id,
            swimmer_id=seeded.ben_id,
            event_id=seeded.event_id,
        ),
    )
    seeded.other_meet_id = other.id
    return seeded


def test_filters(page, two_meets):
    open_app(page)
    expect(page.locator("#entries-body tr.entry")).to_have_count(3)
    # One heading per meet, oldest first: Winter Invite (Jan 10) before Spring Champs (Mar 1),
    # each followed by its own entries.
    headings = page.locator("#entries-body tr.meet-heading .meet-name")
    expect(headings).to_have_text(["Winter Invite", "Spring Champs"])
    kinds = page.locator("#entries-body tr").evaluate_all(
        "rows => rows.map(r => r.classList.contains('meet-heading') ? 'meet-heading' : r.className)"
    )
    assert kinds == ["meet-heading", "entry", "entry", "meet-heading", "entry"]

    page.select_option("#filter-meet", str(two_meets.meet_id))
    expect(page.locator("#entries-body tr.entry")).to_have_count(2)

    page.select_option("#filter-swimmer", str(two_meets.ben_id))
    expect(page.locator("#entries-body tr.entry")).to_have_count(1)

    page.select_option("#filter-meet", "")
    expect(page.locator("#entries-body tr.entry")).to_have_count(2)  # Ben at both meets

    page.select_option("#filter-meet", str(two_meets.other_meet_id))
    page.select_option("#filter-swimmer", str(two_meets.adella_id))
    expect(page.locator("#entries-body tr")).to_have_count(0)  # no empty meet headings either
    expect(page.locator("#entries-empty")).to_have_text("No entries match these filters.")


def test_entries_headers_are_left_aligned(page, seeded):
    open_app(page)
    aligns = page.locator("#view-entries thead th").evaluate_all("ths => ths.map(th => getComputedStyle(th).textAlign)")
    assert set(aligns) <= {"left", "start"}, aligns


def test_collapse_and_expand_a_meet(page, two_meets):
    open_app(page)
    winter = page.get_by_role("button", name="Winter Invite")
    expect(winter).to_have_attribute("aria-expanded", "true")

    winter.click()
    expect(winter).to_have_attribute("aria-expanded", "false")
    expect(winter).to_be_focused()  # focus survives the re-render, for keyboard users
    expect(page.locator("#entries-body tr.entry")).to_have_count(1)  # only Spring Champs' entry is left
    expect(row(page, "entries", "Winter Invite")).to_contain_text("2 entries hidden")
    expect(row(page, "entries", "Spring Champs").locator(".group-count")).to_have_count(0)

    # The choice is remembered across reloads (and filter changes re-render with it).
    page.reload(wait_until="networkidle")
    expect(page.locator("#entries-body tr.entry")).to_have_count(1)
    page.select_option("#filter-swimmer", str(two_meets.ben_id))
    expect(row(page, "entries", "Winter Invite")).to_contain_text("1 entry hidden")

    page.get_by_role("button", name="Winter Invite").press("Enter")
    expect(page.get_by_role("button", name="Winter Invite")).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#entries-body tr.entry")).to_have_count(2)  # Ben at both meets
    expect(page.locator(".group-count")).to_have_count(0)


def test_clicking_meet_or_swimmer_name_filters_entries(page, two_meets):
    open_app(page, "meets")
    row(page, "meets", "Spring Champs").get_by_role("button", name="Spring Champs").click()
    expect(page.locator("#view-entries")).to_be_visible()
    expect(page.locator("#filter-meet")).to_have_value(str(two_meets.other_meet_id))
    expect(page.locator("#entries-body tr.entry")).to_have_count(1)

    page.get_by_role("tab", name="Swimmers").click()
    row(page, "swimmers", "Adella Barber").get_by_role("button", name="Adella Barber").click()
    expect(page.locator("#filter-meet")).to_have_value("")  # swimmer link clears the meet filter
    expect(page.locator("#filter-swimmer")).to_have_value(str(two_meets.adella_id))
    expect(page.locator("#entries-body tr.entry")).to_have_count(1)


# --- entries: add ------------------------------------------------------------


def test_add_entry_needs_a_swimmer_and_a_meet(page, meet):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    expect(toast(page)).to_have_text("Add at least one swimmer and one meet first.")
    expect(page.locator("#entry-dialog")).to_be_hidden()


def test_add_entry_creates_event_and_result(page, swimmer, meet):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    save(
        page,
        "entry-dialog",
        "entry-form",
        meet_id=meet.id,
        swimmer_id=swimmer.id,
        distance=200,
        stroke="BK",
        course="LCM",
        time="2:45.3",
        time_notes="first 200",
    )

    [event] = api(page, "/events/")
    assert event["name"] == "200 BK LCM"
    [entry] = api(page, "/meet_entries/")
    assert entry["event_id"] == event["id"]
    [result] = api(page, "/swim_times/")
    assert (result["meet_entry_id"], result["time_seconds"], result["notes"]) == (entry["id"], 165.3, "first 200")
    expect(row(page, "entries", "200 BK LCM")).to_contain_text("2:45.30")
    expect(toast(page)).to_have_text("Entry added")


# --- entries: DQs and relays -----------------------------------------------------


def test_add_dq_without_a_time(page, swimmer, meet):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    reason = page.locator("#dq-reason-field")
    expect(reason).to_be_hidden()
    page.locator("#entry-form [name=dq]").check()
    expect(reason).to_be_visible()  # the reason field only shows for a DQ
    save(page, "entry-dialog", "entry-form", distance=50, stroke="BK", course="LCM", dq_reason="Scissors kick")

    [result] = api(page, "/swim_times/")
    assert (result["dq"], result["dq_reason"], result["time_seconds"]) == (True, "Scissors kick", None)
    dq_row = row(page, "entries", "50 BK LCM")
    expect(dq_row.locator(".dq-badge")).to_have_text("DQ")
    expect(dq_row.locator(".clock")).to_have_count(0)
    expect(dq_row.locator("td.c-notes")).to_have_text("DQ: Scissors kick")


def test_dq_keeps_the_time_swum_but_shows_it_struck_through(page, swimmer, meet):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    save(page, "entry-dialog", "entry-form", distance=50, stroke="FR", course="LCM", time="42.96", dq=True)
    [result] = api(page, "/swim_times/")
    assert (result["dq"], result["time_seconds"]) == (True, 42.96)
    expect(row(page, "entries", "50 FR LCM").locator(".dq-time")).to_have_text("42.96")


def test_add_relay_leg(page, swimmer, meet):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    form = page.locator("#entry-form")
    expect(page.locator("#relay-fields")).to_be_hidden()

    form.locator("[name=relay]").check()
    expect(page.locator("#relay-fields")).to_be_visible()
    expect(form.locator("[data-relay-text]")).to_have_text("Team time")
    # Relays are Free or Medley: other strokes are disabled, IM reads "Medley".
    expect(form.locator("[name=stroke] option[value=BK]")).to_have_js_property("disabled", True)
    expect(form.locator("[name=stroke] option[value=IM]")).to_have_text("Medley")

    save(
        page, "entry-dialog", "entry-form",
        distance=200, stroke="IM", course="LCM", time="3:04.99", relay_leg=4, split="41.94",
    )  # fmt: skip

    [event] = api(page, "/events/")
    assert (event["name"], event["relay"]) == ("200 MED-R LCM", True)
    [result] = api(page, "/swim_times/")
    assert (result["time_seconds"], result["relay_leg"], result["split_seconds"]) == (184.99, 4, 41.94)
    relay_row = row(page, "entries", "200 MED-R LCM")
    expect(relay_row.locator(".clock")).to_have_text("3:04.99")
    expect(relay_row.locator(".relay-detail")).to_have_text("Leg 4 · split 41.94")

    # Unticking Relay restores the individual strokes and hides the relay fields.
    page.get_by_role("button", name="+ Add entry").click()
    form.locator("[name=relay]").check()
    form.locator("[name=relay]").uncheck()
    expect(form.locator("[name=stroke] option[value=BK]")).to_have_js_property("disabled", False)
    expect(form.locator("[name=stroke] option[value=IM]")).to_have_text("IM")
    expect(page.locator("#relay-fields")).to_be_hidden()


def test_relay_and_individual_events_stay_separate(page, swimmer, meet, swim_event):
    """50 FR SCY exists; entering a 50 FR SCY relay creates a new relay event instead of reusing it."""
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    save(page, "entry-dialog", "entry-form", distance=50, stroke="FR", course="SCY", relay=True, time="1:59.00")
    assert sorted(e["name"] for e in api(page, "/events/")) == ["50 FR SCY", "50 FR-R SCY"]


@pytest.fixture
def relay_dq(db, swimmer, meet):
    event = crud.create_event(db, schemas.EventCreate(distance=200, stroke="FR", course="LCM", relay=True))
    entry = crud.create_meet_entry(
        db, schemas.MeetEntryCreate(meet_id=meet.id, swimmer_id=swimmer.id, event_id=event.id)
    )
    crud.create_swim_time(
        db,
        schemas.SwimTimeCreate(
            meet_entry_id=entry.id, time_seconds=160.5, dq=True, dq_reason="Early take-off swimmer #2",
            relay_leg=3, split_seconds=39.1,
        ),
    )  # fmt: skip
    return entry


def test_edit_relay_dq_prefills_and_can_be_un_dqd(page, relay_dq):
    open_app(page)
    click_row_button(page, "entries", "200 FR-R LCM", "Edit")
    form = page.locator("#entry-form")
    expect(form.locator("[name=relay]")).to_be_checked()
    expect(form.locator("[name=dq]")).to_be_checked()
    expect(form.locator("[name=relay_leg]")).to_have_value("3")
    expect(form.locator("[name=split]")).to_have_value("39.10")
    expect(form.locator("[name=time]")).to_have_value("2:40.50")
    expect(form.locator("[name=dq_reason]")).to_have_value("Early take-off swimmer #2")
    expect(page.locator("#relay-fields")).to_be_visible()
    expect(page.locator("#dq-reason-field")).to_be_visible()

    save(page, "entry-dialog", "entry-form", dq=False)
    [result] = api(page, "/swim_times/")
    assert (result["dq"], result["dq_reason"], result["time_seconds"], result["relay_leg"]) == (False, None, 160.5, 3)
    expect(row(page, "entries", "200 FR-R LCM").locator(".clock")).to_have_text("2:40.50")


@pytest.mark.parametrize(
    "fields", [{"time_notes": "x"}, {"relay": True, "relay_leg": 2}, {"relay": True, "split": "30.00"}]
)
def test_result_details_need_a_time_or_dq(page, swimmer, meet, fields):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    fill(page, "entry-form", distance=100, stroke="FR", course="SCY", **fields)
    page.locator("#entry-form button[type=submit]").click()
    expect(page.locator("#entry-form .form-error")).to_have_text(
        "Enter a time (or mark it a DQ) to save the result details."
    )
    assert api(page, "/meet_entries/") == []


def test_add_entry_reuses_existing_event_and_allows_no_time(page, swimmer, meet, swim_event):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    save(page, "entry-dialog", "entry-form", distance=50, stroke="FR", course="SCY", time="")
    assert len(api(page, "/events/")) == 1
    assert api(page, "/meet_entries/")[0]["event_id"] == swim_event.id
    assert api(page, "/swim_times/") == []
    expect(row(page, "entries", "50 FR SCY")).to_contain_text("—")


def test_new_entry_defaults_to_current_filters_and_last_course(page, two_meets):
    open_app(page)
    page.select_option("#filter-meet", str(two_meets.other_meet_id))
    page.select_option("#filter-swimmer", str(two_meets.adella_id))
    page.get_by_role("button", name="+ Add entry").click()
    expect(page.locator("#entry-form [name=meet_id]")).to_have_value(str(two_meets.other_meet_id))
    expect(page.locator("#entry-form [name=swimmer_id]")).to_have_value(str(two_meets.adella_id))
    expect(page.locator("#entry-form [name=distance]")).to_have_value("50")
    expect(page.locator("#entry-form [name=course]")).to_have_value("SCY")

    save(page, "entry-dialog", "entry-form", distance=100, stroke="FL", course="LCM")
    page.get_by_role("button", name="+ Add entry").click()
    expect(page.locator("#entry-form [name=course]")).to_have_value("LCM")
    expect(page.locator("#entry-form [name=time]")).to_have_value("")  # reset from last time


@pytest.mark.parametrize(
    "fields, error",
    [
        ({"time": "1:75.00"}, "seconds must be under 60"),
        ({"time": "fast"}, "isn't a valid time"),
        ({"time": "", "time_notes": "PB"}, "Enter a time (or mark it a DQ) to save the result details."),
    ],
)
def test_invalid_entry_shows_error_and_writes_nothing(page, swimmer, meet, fields, error):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    fill(page, "entry-form", **fields)
    page.locator("#entry-form button[type=submit]").click()
    expect(page.locator("#entry-form .form-error")).to_contain_text(error)
    expect(page.locator("#entry-dialog")).to_be_visible()
    assert api(page, "/meet_entries/") == []
    assert api(page, "/events/") == []


def test_duplicate_entry_shows_server_error(page, meet_entry):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    fill(page, "entry-form", distance=50, stroke="FR", course="SCY")
    page.locator("#entry-form button[type=submit]").click()
    expect(page.locator("#entry-form .form-error")).to_have_text(
        "This swimmer is already entered in this event at this meet"
    )
    expect(page.locator("#entry-dialog")).to_be_visible()
    assert len(api(page, "/meet_entries/")) == 1


def test_retry_after_failed_result_save_does_not_duplicate_entry(page, swimmer, meet):
    """If the entry saves but the result POST fails, the dialog stays open;
    pressing Save again must update that entry, not try to create another."""
    failures = []

    def fail_first_time_post(route):
        if route.request.method == "POST" and not failures:
            failures.append(1)
            route.fulfill(status=500, json={"detail": "temporary glitch"})
        else:
            route.continue_()

    page.route("**/swim_times/", fail_first_time_post)
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    fill(page, "entry-form", distance=100, stroke="FR", course="SCY", time="1:05.00")
    page.locator("#entry-form button[type=submit]").click()
    expect(page.locator("#entry-form .form-error")).to_have_text("temporary glitch")
    assert len(api(page, "/meet_entries/")) == 1

    page.locator("#entry-form button[type=submit]").click()
    expect(page.locator("#entry-dialog")).to_be_hidden()
    [entry] = api(page, "/meet_entries/")
    [result] = api(page, "/swim_times/")
    assert (result["meet_entry_id"], result["time_seconds"]) == (entry["id"], 65.0)


# --- entries: edit & delete --------------------------------------------------


def test_edit_entry_prefills_and_updates_result(page, seeded):
    open_app(page)
    click_row_button(page, "entries", "Adella Barber", "Edit")
    form = "#entry-form"
    expect(page.locator("#entry-dialog h2")).to_have_text("Edit entry")
    expect(page.locator(f"{form} [name=swimmer_id]")).to_have_value(str(seeded.adella_id))
    expect(page.locator(f"{form} [name=distance]")).to_have_value("50")
    expect(page.locator(f"{form} [name=stroke]")).to_have_value("FR")
    expect(page.locator(f"{form} [name=course]")).to_have_value("SCY")
    expect(page.locator(f"{form} [name=time]")).to_have_value("32.45")
    expect(page.locator(f"{form} [name=time_notes]")).to_have_value("PB")

    save(page, "entry-dialog", "entry-form", time="31.9", time_notes="")
    [result] = api(page, "/swim_times/")
    assert (result["meet_entry_id"], result["time_seconds"], result["notes"]) == (seeded.adella_entry_id, 31.9, None)
    expect(row(page, "entries", "Adella Barber")).to_contain_text("31.90")
    expect(toast(page)).to_have_text("Entry updated")


def test_clearing_time_deletes_result_but_keeps_entry(page, seeded):
    open_app(page)
    click_row_button(page, "entries", "Adella Barber", "Edit")
    save(page, "entry-dialog", "entry-form", time="", time_notes="")
    assert api(page, "/swim_times/") == []
    assert len(api(page, "/meet_entries/")) == 2
    expect(row(page, "entries", "Adella Barber").get_by_role("button", name="Add time")).to_be_visible()


def test_add_time_to_untimed_entry(page, seeded):
    open_app(page)
    click_row_button(page, "entries", "Ben Cho", "Add time")
    expect(page.locator("#entry-form [name=time]")).to_have_value("")
    save(page, "entry-dialog", "entry-form", time="29.5")
    times = {t["meet_entry_id"]: t["time_seconds"] for t in api(page, "/swim_times/")}
    assert times == {seeded.adella_entry_id: 32.45, seeded.ben_entry_id: 29.5}


def test_edit_entry_changes_swimmer_and_event(page, seeded, db):
    other = crud.create_swimmer(db, schemas.SwimmerCreate(name="Cara Diaz", birthdate=date(2015, 1, 1), gender="F"))
    open_app(page)
    click_row_button(page, "entries", "Adella Barber", "Edit")
    save(page, "entry-dialog", "entry-form", swimmer_id=other.id, distance=100, stroke="IM")
    entry = next(e for e in api(page, "/meet_entries/") if e["id"] == seeded.adella_entry_id)
    event = next(e for e in api(page, "/events/") if e["id"] == entry["event_id"])
    assert (entry["swimmer_id"], event["name"]) == (other.id, "100 IM SCY")
    assert api(page, "/swim_times/")[0]["meet_entry_id"] == seeded.adella_entry_id  # result follows the entry


def test_delete_entry_with_result(page, seeded, confirms):
    open_app(page)
    click_row_button(page, "entries", "Adella Barber", "Delete")
    expect(toast(page)).to_have_text("Entry deleted")
    assert confirms.messages == [
        "Delete Adella Barber's 50 FR SCY entry at Winter Invite?\n\nIts recorded time will also be deleted."
    ]
    assert [e["id"] for e in api(page, "/meet_entries/")] == [seeded.ben_entry_id]
    assert api(page, "/swim_times/") == []


def test_delete_entry_without_result(page, seeded, confirms):
    open_app(page)
    click_row_button(page, "entries", "Ben Cho", "Delete")
    expect(toast(page)).to_have_text("Entry deleted")
    assert confirms.messages == ["Delete Ben Cho's 50 FR SCY entry at Winter Invite?"]
    assert len(api(page, "/swim_times/")) == 1


# --- importing a results PDF -------------------------------------------------

PDF_FILE = {"name": "results.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.7 fake"}


@pytest.fixture
def fake_results_pdf(monkeypatch):
    """Any uploaded PDF parses as test_import_meet_results.results_pages():
    Adella Barber 50 FR SCY 29.50 and Sam Lee 100 FL LCM 1:05.10."""
    import import_meet_results as imr
    from conftest import FakePDF
    from test_import_meet_results import results_pages

    monkeypatch.setattr(imr.pdfplumber, "open", lambda f: FakePDF(results_pages()))


def import_pdf(page, meet_id, file=PDF_FILE):
    page.get_by_role("button", name="Import results").click()
    fill(page, "import-form", meet_id=meet_id)
    page.locator("#import-form [name=pdf]").set_input_files(file)
    page.locator("#import-form button[type=submit]").click()


def test_import_results_adds_times_and_missing_entries(page, db, swimmer, meet, fake_results_pdf):
    sam = crud.create_swimmer(db, schemas.SwimmerCreate(name="Sam Lee", birthdate=date(2012, 3, 1), gender="M"))
    fly = crud.create_event(db, schemas.EventCreate(distance=100, stroke="FL", course="LCM"))
    crud.create_meet_entry(db, schemas.MeetEntryCreate(meet_id=meet.id, swimmer_id=sam.id, event_id=fly.id))
    open_app(page)

    import_pdf(page, meet.id)

    expect(page.locator("#import-dialog")).to_be_hidden()
    expect(toast(page)).to_have_text("Imported 2 times (1 new entry).")
    expect(row(page, "entries", "Adella Barber")).to_contain_text("29.50")
    expect(row(page, "entries", "Sam Lee")).to_contain_text("1:05.10")
    assert page.locator("#filter-meet").input_value() == str(meet.id)
    assert len(api(page, "/meet_entries/")) == 2  # Sam's existing entry was reused
    assert len(api(page, "/swim_times/")) == 2


def test_import_results_twice_reports_already_recorded(page, swimmer, meet, fake_results_pdf):
    open_app(page)
    import_pdf(page, meet.id)
    expect(page.locator("#import-dialog")).to_be_hidden()
    import_pdf(page, meet.id)
    expect(page.locator("#import-dialog")).to_be_hidden()
    expect(toast(page)).to_have_text("1 result was already recorded.")
    assert len(api(page, "/swim_times/")) == 1


def test_import_results_defaults_to_filtered_meet(page, two_meets):
    open_app(page)
    page.locator("#filter-meet").select_option(str(two_meets.other_meet_id))
    page.get_by_role("button", name="Import results").click()
    assert page.locator("#import-form [name=meet_id]").input_value() == str(two_meets.other_meet_id)


def test_import_results_rejects_non_pdf(page, swimmer, meet):
    open_app(page)
    import_pdf(page, meet.id, {"name": "notes.pdf", "mimeType": "application/pdf", "buffer": b"hello"})
    expect(page.locator("#import-form .form-error")).to_have_text("The uploaded file isn't a PDF.")
    expect(page.locator("#import-dialog")).to_be_visible()
    assert api(page, "/meet_entries/") == []


def test_import_results_needs_a_meet(page):
    open_app(page)
    page.get_by_role("button", name="Import results").click()
    expect(toast(page)).to_have_text("Add the meet on the Meets tab first.")
    expect(page.locator("#import-dialog")).to_be_hidden()


# --- time standards ------------------------------------------------------------


@pytest.fixture
def standards(db):
    """USA (tiers inserted out of rank order, one tier missing) and MN, over three events."""

    def event(distance, stroke, course):
        return crud.create_event(db, schemas.EventCreate(distance=distance, stroke=stroke, course=course)).id

    free_scy, free_lcm, back_scy = event(50, "FR", "SCY"), event(50, "FR", "LCM"), event(100, "BK", "SCY")

    def add(event_id, org, season, age, gender, tier, rank, seconds):
        crud.create_time_standard(
            db,
            schemas.TimeStandardCreate(
                event_id=event_id,
                organization=org,
                season=season,
                age_group=age,
                gender=gender,
                standard_name=tier,
                standard_rank=rank,
                time_seconds=seconds,
            ),
        )

    usa = ("USA Swimming", "2024-2028")
    for age in ("11-12", "10 & under"):
        for gender in ("M", "F"):
            for tier, rank, secs in (("A", 3, 30.09), ("B", 1, 35.19), ("BB", 2, 32.59)):
                add(free_scy, *usa, age, gender, tier, rank, secs)
    add(free_lcm, *usa, "11-12", "F", "B", 1, 40.29)  # only a B time for this event
    add(back_scy, *usa, "11-12", "F", "B", 1, 65.1)
    add(free_scy, "MN Swimming", "2025-2026", "11-12", "F", "GOLD", 3, 31.19)
    add(free_lcm, "MN Swimming", "2025-2026", "8 & Under", "M", "GOLD", 3, 50.5)  # an age group USA doesn't have


def std_rows(page):
    return page.locator("#standards-body tr.standard")


def pick_standard(page, label):
    page.select_option("#standard-set", label=label)
    expect(page.locator("#standards-table")).to_be_visible()


def test_standards_start_with_no_standard_selected(page, standards):
    open_app(page, "standards")
    select = page.locator("#standard-set")
    assert select.input_value() == ""
    assert select.evaluate("s => s.multiple") is False
    options = select.locator("option")
    expect(options).to_have_text(["Select a standard…", "MN Swimming (2025-2026)", "USA Swimming (2024-2028)"])
    assert options.first.evaluate("o => o.disabled")  # no "all" choice, and the placeholder can't be picked
    for f in ("distance", "stroke", "course"):
        expect(page.locator(f"#standard-{f}")).to_be_disabled()
    expect(page.locator("#standards-empty")).to_have_text("Select a standard to see its times.")
    expect(page.locator("#standards-table")).to_be_hidden()


def test_standard_shows_tiers_in_rank_order_grouped_by_age(page, standards):
    open_app(page, "standards")
    pick_standard(page, "USA Swimming (2024-2028)")

    expect(page.locator("#standards-head th")).to_have_text(["Event", "Gender", "B", "BB", "A"])
    expect(page.locator("#standards-body tr.age-heading")).to_have_text(["10 & under", "11-12"])
    first = std_rows(page).first
    expect(first.locator("td")).to_have_text(["50 FR SCY", "Girls", "35.19", "32.59", "30.09"])
    expect(page.locator("#standards-body tr").filter(has_text="50 FR LCM").locator("td")).to_have_text(
        ["50 FR LCM", "Girls", "40.29", "—", "—"]
    )
    expect(page.locator("#standards-body tr").filter(has_text="100 BK SCY")).to_contain_text("1:05.10")
    aligns = page.locator("#standards-head th").evaluate_all("ths => ths.map(th => getComputedStyle(th).textAlign)")
    assert set(aligns) <= {"left", "start"}, aligns


def test_standard_filters_combine(page, standards):
    open_app(page, "standards")
    pick_standard(page, "USA Swimming (2024-2028)")
    expect(std_rows(page)).to_have_count(6)  # 4 x 50 FR SCY, 50 FR LCM, 100 BK SCY

    # Choices come from the selected standard's events.
    expect(page.locator("#standard-distance option")).to_have_text(["All", "50", "100"])
    expect(page.locator("#standard-stroke option")).to_have_text(["All", "Free (FR)", "Back (BK)"])
    expect(page.locator("#standard-course option")).to_have_text(["All", "SCY", "LCM"])

    page.select_option("#standard-distance", "50")
    expect(std_rows(page)).to_have_count(5)
    page.select_option("#standard-course", "LCM")
    expect(std_rows(page)).to_have_count(1)
    page.select_option("#standard-distance", "")
    page.select_option("#standard-stroke", "BK")
    expect(std_rows(page)).to_have_count(0)
    expect(page.locator("#standards-empty")).to_have_text("No standards match these filters.")
    page.select_option("#standard-course", "SCY")
    expect(std_rows(page)).to_have_count(1)
    expect(std_rows(page)).to_contain_text("100 BK SCY")


def test_switching_standard_shows_only_that_one(page, standards):
    open_app(page, "standards")
    pick_standard(page, "USA Swimming (2024-2028)")
    page.select_option("#standard-stroke", "BK")
    pick_standard(page, "MN Swimming (2025-2026)")

    expect(page.locator("#standards-head th")).to_have_text(["Event", "Gender", "GOLD"])
    expect(page.locator("#standard-stroke")).to_have_value("")  # MN has no BK here, so the filter resets
    expect(std_rows(page)).to_have_count(2)
    expect(std_rows(page).filter(has_text="SCY").locator("td")).to_have_text(["50 FR SCY", "Girls", "31.19"])


def test_standard_selection_is_not_remembered_across_loads(page, standards):
    open_app(page, "standards")
    pick_standard(page, "MN Swimming (2025-2026)")
    page.reload(wait_until="networkidle")
    expect(page.locator("#standard-set")).to_have_value("")
    expect(page.locator("#standards-table")).to_be_hidden()


def test_no_standards_loaded(page):
    open_app(page, "standards")
    expect(page.locator("#standards-empty")).to_contain_text("No time standards loaded yet")
    expect(page.locator("#standard-set option")).to_have_count(1)


def test_standards_table_scrolls_inside_its_box_on_phone(page, standards):
    page.set_viewport_size({"width": 375, "height": 800})
    open_app(page, "standards")
    pick_standard(page, "USA Swimming (2024-2028)")
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0


# --- time standards: gender, age groups, collapsing ------------------------------


def age_boxes(page):
    return page.locator("#standard-age-options label")


def open_age_menu(page):
    page.locator("#standard-age summary").click()
    expect(page.locator("#standard-age .multiselect-menu")).to_be_visible()


def tick_age(page, age):
    page.locator("#standard-age-options label").filter(has_text=age).locator("input").click()


def age_headings(page):
    return page.locator("#standards-body tr.age-heading .age-name")


def test_gender_and_age_choices_come_from_the_selected_standard(page, standards):
    open_app(page, "standards")
    expect(page.locator("#standard-gender")).to_be_disabled()
    page.locator("#standard-age summary").click()  # disabled: doesn't open
    expect(page.locator("#standard-age .multiselect-menu")).to_be_hidden()

    pick_standard(page, "USA Swimming (2024-2028)")
    expect(page.locator("#standard-gender option")).to_have_text(["All", "Girls", "Boys"])
    open_age_menu(page)
    expect(age_boxes(page)).to_have_text(["10 & under", "11-12"])  # no "8 & Under" for USA

    pick_standard(page, "MN Swimming (2025-2026)")
    open_age_menu(page)
    expect(age_boxes(page)).to_have_text(["8 & Under", "11-12"])


def test_gender_filter(page, standards):
    open_app(page, "standards")
    pick_standard(page, "USA Swimming (2024-2028)")
    page.select_option("#standard-gender", "M")
    expect(std_rows(page)).to_have_count(2)  # 50 FR SCY Boys in each age group
    for gender in std_rows(page).locator("td.c-gender").all_inner_texts():
        assert gender == "Boys"


def test_age_groups_multiselect(page, standards):
    open_app(page, "standards")
    pick_standard(page, "USA Swimming (2024-2028)")
    expect(page.locator("#standard-age-summary")).to_have_text("All")

    open_age_menu(page)
    tick_age(page, "11-12")
    expect(age_headings(page)).to_have_text(["11-12"])
    expect(page.locator("#standard-age-summary")).to_have_text("11-12")
    expect(page.locator("#standard-age-options input[value='11-12']")).to_be_focused()  # focus kept after re-render

    tick_age(page, "10 & under")  # aging up: see both groups side by side
    expect(age_headings(page)).to_have_text(["10 & under", "11-12"])
    expect(page.locator("#standard-age-summary")).to_have_text("10 & under, 11-12")

    page.get_by_role("button", name="Show all age groups").click()
    expect(page.locator("#standard-age .multiselect-menu")).to_be_hidden()
    expect(page.locator("#standard-age-summary")).to_have_text("All")
    expect(std_rows(page)).to_have_count(6)


def test_ticked_age_group_carries_over_only_if_the_new_standard_has_it(page, standards):
    open_app(page, "standards")
    pick_standard(page, "USA Swimming (2024-2028)")
    open_age_menu(page)
    tick_age(page, "11-12")
    tick_age(page, "10 & under")
    page.keyboard.press("Escape")
    expect(page.locator("#standard-age .multiselect-menu")).to_be_hidden()

    pick_standard(page, "MN Swimming (2025-2026)")
    expect(page.locator("#standard-age-summary")).to_have_text("11-12")  # MN has no "10 & under"
    expect(age_headings(page)).to_have_text(["11-12"])


def test_age_menu_closes_on_outside_click(page, standards):
    open_app(page, "standards")
    pick_standard(page, "USA Swimming (2024-2028)")
    open_age_menu(page)
    page.locator("#standards-empty, #standards-table").first.click(position={"x": 5, "y": 5})
    expect(page.locator("#standard-age .multiselect-menu")).to_be_hidden()


def test_collapse_age_groups(page, standards):
    open_app(page, "standards")
    pick_standard(page, "USA Swimming (2024-2028)")
    under10 = page.get_by_role("button", name="10 & under")
    expect(under10).to_have_attribute("aria-expanded", "true")

    under10.click()
    expect(under10).to_have_attribute("aria-expanded", "false")
    expect(under10).to_be_focused()
    expect(std_rows(page)).to_have_count(4)  # only 11-12's rows
    expect(page.locator("#standards-body tr.age-heading").first).to_contain_text("2 standards hidden")

    # Remembered for this standard across loads.
    page.reload(wait_until="networkidle")
    pick_standard(page, "USA Swimming (2024-2028)")
    expect(std_rows(page)).to_have_count(4)

    # With a single age group on screen there's nothing to collapse: it always shows its rows.
    open_age_menu(page)
    tick_age(page, "10 & under")
    expect(page.locator("#standards-body .group-toggle")).to_have_count(0)
    expect(std_rows(page)).to_have_count(2)

    page.get_by_role("button", name="Show all age groups").click()
    page.get_by_role("button", name="10 & under").click()
    expect(std_rows(page)).to_have_count(6)
    expect(page.locator(".group-count")).to_have_count(0)


# --- entries: compare to a standard ------------------------------------------------


@pytest.fixture
def entry_standards(db, seeded):
    """USA 11-12/13-14 Girls and MN 11-12 Girls standards for the seeded 50 FR SCY.
    Adella (born 2014-05-01) swam 32.45 at Winter Invite (2026-01-10), aged 11."""

    def add(org, season, age, tier, rank, seconds, gender="F"):
        crud.create_time_standard(
            db,
            schemas.TimeStandardCreate(
                event_id=seeded.event_id, organization=org, season=season, age_group=age,
                gender=gender, standard_name=tier, standard_rank=rank, time_seconds=seconds,
            ),
        )  # fmt: skip

    for tier, rank, secs in (("B", 1, 35.19), ("BB", 2, 32.59), ("A", 3, 30.09)):
        add("USA Swimming", "2024-2028", "11-12", tier, rank, secs)
    for tier, rank, secs in (("B", 1, 33.0), ("A", 3, 29.0)):
        add("USA Swimming", "2024-2028", "13-14", tier, rank, secs)
    for tier, rank, secs in (("SLVR", 2, 35.39), ("GOLD", 3, 31.19)):
        add("MN Swimming", "2025-2026", "11-12", tier, rank, secs)
    return seeded


def standing(page, swimmer):
    return row(page, "entries", swimmer).locator("td.c-standing")


def compare_to(page, label):
    page.select_option("#entries-standard", label=label)


def test_standard_column_shows_reached_and_next(page, entry_standards):
    open_app(page)
    expect(page.locator("#entries-standard option")).to_have_text(
        ["No standard", "MN Swimming (2025-2026)", "USA Swimming (2024-2028)"]
    )
    expect(page.locator("#entries-table th.c-standing")).to_be_hidden()  # no standard chosen yet

    compare_to(page, "USA Swimming (2024-2028)")
    expect(page.locator("#entries-table th.c-standing")).to_be_visible()
    adella = standing(page, "Adella Barber")
    expect(adella.locator(".std-badge")).to_have_text("BB")
    expect(adella.locator(".std-next")).to_have_text("2.36 to A (30.09)")
    expect(adella).to_have_attribute("title", "Age 11 at this meet: 11-12")
    expect(standing(page, "Ben Cho")).to_have_text("")  # no time yet

    compare_to(page, "MN Swimming (2025-2026)")
    expect(adella.locator(".std-badge")).to_have_text("SLVR")
    expect(adella.locator(".std-next")).to_have_text("1.26 to GOLD (31.19)")

    compare_to(page, "No standard")
    expect(page.locator("#entries-table th.c-standing")).to_be_hidden()


def test_standard_choice_is_remembered(page, entry_standards):
    open_app(page)
    compare_to(page, "USA Swimming (2024-2028)")
    page.reload(wait_until="networkidle")
    expect(page.locator("#entries-standard")).to_have_value("USA Swimming|2024-2028")
    expect(standing(page, "Adella Barber").locator(".std-badge")).to_have_text("BB")


@pytest.mark.parametrize(
    "seconds, badge, next_text",
    [
        (29.5, "A", "Top standard"),
        (36.0, None, "0.81 to B (35.19)"),  # hasn't reached the first tier yet
    ],
)
def test_standard_top_and_not_yet(page, db, entry_standards, seconds, badge, next_text):
    crud.update_swim_time(db, 1, schemas.SwimTimeUpdate(time_seconds=seconds))
    open_app(page)
    compare_to(page, "USA Swimming (2024-2028)")
    cell = standing(page, "Adella Barber")
    expect(cell.locator(".std-next")).to_have_text(next_text)
    if badge:
        expect(cell.locator(".std-badge")).to_have_text(badge)
    else:
        expect(cell.locator(".std-badge")).to_have_count(0)


def test_standard_uses_age_on_the_meet_date(page, db, entry_standards):
    """The same swimmer at a later meet, after turning 13, is compared to 13-14."""
    later = crud.create_meet(db, schemas.MeetCreate(name="Summer Champs", date=date(2027, 7, 1)))
    entry = crud.create_meet_entry(
        db,
        schemas.MeetEntryCreate(
            meet_id=later.id, swimmer_id=entry_standards.adella_id, event_id=entry_standards.event_id
        ),
    )
    crud.create_swim_time(db, schemas.SwimTimeCreate(meet_entry_id=entry.id, time_seconds=30.0))
    open_app(page)
    page.select_option("#filter-meet", str(later.id))
    compare_to(page, "USA Swimming (2024-2028)")
    cell = standing(page, "Adella Barber")
    expect(cell).to_have_attribute("title", "Age 13 at this meet: 13-14")
    expect(cell.locator(".std-badge")).to_have_text("B")
    expect(cell.locator(".std-next")).to_have_text("1.00 to A (29.00)")


def test_standard_blank_for_dq_and_missing_standards(page, db, entry_standards):
    crud.update_swim_time(db, 1, schemas.SwimTimeUpdate(dq=True, dq_reason="False start", time_seconds=None))
    open_app(page)
    compare_to(page, "USA Swimming (2024-2028)")
    expect(standing(page, "Adella Barber")).to_have_text("")  # a DQ isn't compared

    # Ben is a boy: these standards are Girls only, so there's nothing to compare to.
    crud.create_swim_time(db, schemas.SwimTimeCreate(meet_entry_id=entry_standards.ben_entry_id, time_seconds=33.0))
    page.reload(wait_until="networkidle")
    ben = standing(page, "Ben Cho")
    expect(ben.locator(".std-none")).to_have_text("—")
    expect(ben).to_have_attribute("title", "No standard for 50 FR SCY, 13-14")
