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
        adella_id=swimmer.id, ben_id=ben.id, meet_id=meet.id, event_id=swim_event.id,
        adella_entry_id=meet_entry.id, ben_entry_id=ben_entry.id,
    )


# --- rendering & navigation --------------------------------------------------

def test_renders_seeded_entries(page, seeded):
    open_app(page)
    expect(page.locator("#entries-body tr")).to_have_count(2)
    adella = row(page, "entries", "Adella Barber")
    for text in ("Winter Invite", "Jan 10, 2026", "50 FR SCY", "32.45", "PB"):
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
    crud.create_swimmer(db, schemas.SwimmerCreate(
        name="<img src=x onerror=window.pwned=1>", birthdate=date(2014, 1, 1), gender="F", notes="<b>bold</b>",
    ))
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
    crud.create_swimmer(db, schemas.SwimmerCreate(
        name="Ann Lee", birthdate=date(2013, 2, 3), gender="F", notes="likes fly"
    ))
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


def test_meets_sorted_newest_first(page, db):
    for name, d in [("Old", date(2025, 1, 1)), ("New", date(2026, 6, 1)), ("Mid", date(2025, 9, 1))]:
        crud.create_meet(db, schemas.MeetCreate(name=name, date=d))
    open_app(page, "meets")
    expect(page.locator("#meets-body tr td:nth-child(2)")).to_have_text(["New", "Mid", "Old"])


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
    crud.create_meet_entry(db, schemas.MeetEntryCreate(
        meet_id=other.id, swimmer_id=seeded.ben_id, event_id=seeded.event_id,
    ))
    seeded.other_meet_id = other.id
    return seeded


def test_filters(page, two_meets):
    open_app(page)
    expect(page.locator("#entries-body tr")).to_have_count(3)
    # newest meet first
    expect(page.locator("#entries-body tr").first).to_contain_text("Spring Champs")

    page.select_option("#filter-meet", str(two_meets.meet_id))
    expect(page.locator("#entries-body tr")).to_have_count(2)

    page.select_option("#filter-swimmer", str(two_meets.ben_id))
    expect(page.locator("#entries-body tr")).to_have_count(1)

    page.select_option("#filter-meet", "")
    expect(page.locator("#entries-body tr")).to_have_count(2)  # Ben at both meets

    page.select_option("#filter-meet", str(two_meets.other_meet_id))
    page.select_option("#filter-swimmer", str(two_meets.adella_id))
    expect(page.locator("#entries-body tr")).to_have_count(0)
    expect(page.locator("#entries-empty")).to_have_text("No entries match these filters.")


def test_clicking_meet_or_swimmer_name_filters_entries(page, two_meets):
    open_app(page, "meets")
    row(page, "meets", "Spring Champs").get_by_role("button", name="Spring Champs").click()
    expect(page.locator("#view-entries")).to_be_visible()
    expect(page.locator("#filter-meet")).to_have_value(str(two_meets.other_meet_id))
    expect(page.locator("#entries-body tr")).to_have_count(1)

    page.get_by_role("tab", name="Swimmers").click()
    row(page, "swimmers", "Adella Barber").get_by_role("button", name="Adella Barber").click()
    expect(page.locator("#filter-meet")).to_have_value("")  # swimmer link clears the meet filter
    expect(page.locator("#filter-swimmer")).to_have_value(str(two_meets.adella_id))
    expect(page.locator("#entries-body tr")).to_have_count(1)


# --- entries: add ------------------------------------------------------------

def test_add_entry_needs_a_swimmer_and_a_meet(page, meet):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    expect(toast(page)).to_have_text("Add at least one swimmer and one meet first.")
    expect(page.locator("#entry-dialog")).to_be_hidden()


def test_add_entry_creates_event_and_result(page, swimmer, meet):
    open_app(page)
    page.get_by_role("button", name="+ Add entry").click()
    save(page, "entry-dialog", "entry-form",
         meet_id=meet.id, swimmer_id=swimmer.id, distance=200, stroke="BK", course="LCM",
         time="2:45.3", time_notes="first 200")

    [event] = api(page, "/events/")
    assert event["name"] == "200 BK LCM"
    [entry] = api(page, "/meet_entries/")
    assert entry["event_id"] == event["id"]
    [result] = api(page, "/swim_times/")
    assert (result["meet_entry_id"], result["time_seconds"], result["notes"]) == (entry["id"], 165.3, "first 200")
    expect(row(page, "entries", "200 BK LCM")).to_contain_text("2:45.30")
    expect(toast(page)).to_have_text("Entry added")


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


@pytest.mark.parametrize("fields, error", [
    ({"time": "1:75.00"}, "seconds must be under 60"),
    ({"time": "fast"}, "isn't a valid time"),
    ({"time": "", "time_notes": "PB"}, "Enter a time to save result notes."),
])
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
