import pytest


def test_root(client):
    assert client.get("/").json() == {"status": "running"}


# --- swimmers --------------------------------------------------------------

def test_swimmer_create_list_patch(client):
    r = client.post("/swimmers/", json={"name": "Ann Lee", "birthdate": "2013-02-03", "gender": "F"})
    assert r.status_code == 200
    swimmer = r.json()
    assert swimmer["id"] and swimmer["notes"] is None

    assert [s["name"] for s in client.get("/swimmers/").json()] == ["Ann Lee"]

    r = client.patch(f"/swimmers/{swimmer['id']}", json={"notes": "fast"})
    assert r.status_code == 200
    assert r.json()["notes"] == "fast"
    assert r.json()["name"] == "Ann Lee"  # untouched fields preserved


def test_swimmer_rejects_unknown_gender(client):
    r = client.post("/swimmers/", json={"name": "X", "birthdate": "2013-02-03", "gender": "Female"})
    assert r.status_code == 422


def test_swimmer_patch_missing(client):
    assert client.patch("/swimmers/999", json={"notes": "x"}).status_code == 404


def test_swimmer_patch_rejects_null_on_required_field(client, swimmer):
    assert client.patch(f"/swimmers/{swimmer.id}", json={"name": None}).status_code == 422


def test_swimmer_patch_allows_null_on_optional_field(client, swimmer):
    r = client.patch(f"/swimmers/{swimmer.id}", json={"notes": None})
    assert r.status_code == 200


# --- meets -----------------------------------------------------------------

def test_meet_create_list_patch(client):
    r = client.post("/meets/", json={"name": "Invite", "date": "2026-01-10"})
    meet = r.json()
    assert r.status_code == 200 and meet["location"] is None

    assert len(client.get("/meets/").json()) == 1

    r = client.patch(f"/meets/{meet['id']}", json={"location": "Pool"})
    assert r.json()["location"] == "Pool"


def test_meet_patch_missing(client):
    assert client.patch("/meets/999", json={"location": "x"}).status_code == 404


def test_meet_patch_rejects_null_date(client, meet):
    assert client.patch(f"/meets/{meet.id}", json={"date": None}).status_code == 422


# --- events ----------------------------------------------------------------

def test_event_create_and_list(client):
    r = client.post("/events/", json={"distance": 100, "stroke": "BK", "course": "LCM"})
    assert r.status_code == 200
    assert r.json()["name"] == "100 BK LCM"
    assert [e["name"] for e in client.get("/events/").json()] == ["100 BK LCM"]


def test_event_duplicate(client, swim_event):
    r = client.post("/events/", json={"distance": 50, "stroke": "FR", "course": "SCY"})
    assert r.status_code == 400
    assert "50 FR SCY" in r.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"distance": 0, "stroke": "FR", "course": "SCY"},
    {"distance": 50, "stroke": "XX", "course": "SCY"},
    {"distance": 50, "stroke": "FR", "course": "YDS"},
])
def test_event_validation(client, payload):
    assert client.post("/events/", json=payload).status_code == 422


# --- meet entries ----------------------------------------------------------

def test_meet_entry_create(client, swimmer, meet, swim_event):
    payload = {"meet_id": meet.id, "swimmer_id": swimmer.id, "event_id": swim_event.id}
    r = client.post("/meet_entries/", json=payload)
    assert r.status_code == 200
    assert r.json() == {**payload, "id": r.json()["id"]}

    # duplicate
    assert client.post("/meet_entries/", json=payload).status_code == 400


@pytest.mark.parametrize("bad_field, label", [
    ("swimmer_id", "Swimmer"), ("meet_id", "Meet"), ("event_id", "Event"),
])
def test_meet_entry_create_missing_fk(client, swimmer, meet, swim_event, bad_field, label):
    payload = {"meet_id": meet.id, "swimmer_id": swimmer.id, "event_id": swim_event.id, bad_field: 999}
    r = client.post("/meet_entries/", json=payload)
    assert r.status_code == 404
    assert r.json()["detail"] == f"{label} 999 not found"


def test_meet_entry_list_filters(client, db, meet_entry, meet, swimmer):
    assert len(client.get("/meet_entries/").json()) == 1
    assert len(client.get("/meet_entries/", params={"meet_id": meet.id}).json()) == 1
    assert len(client.get("/meet_entries/", params={"swimmer_id": swimmer.id}).json()) == 1
    assert client.get("/meet_entries/", params={"meet_id": 999}).json() == []
    assert client.get("/meet_entries/", params={"swimmer_id": 999}).json() == []


def test_meet_entry_patch(client, meet_entry):
    r = client.post("/events/", json={"distance": 100, "stroke": "FL", "course": "SCY"})
    new_event_id = r.json()["id"]
    r = client.patch(f"/meet_entries/{meet_entry.id}", json={"event_id": new_event_id})
    assert r.status_code == 200
    assert r.json()["event_id"] == new_event_id


def test_meet_entry_patch_empty_body_is_noop(client, meet_entry):
    r = client.patch(f"/meet_entries/{meet_entry.id}", json={})
    assert r.status_code == 200
    assert r.json()["event_id"] == meet_entry.event_id


def test_meet_entry_patch_to_same_values_is_allowed(client, meet_entry):
    # The uniqueness check must not flag the entry as a duplicate of itself.
    r = client.patch(f"/meet_entries/{meet_entry.id}", json={"event_id": meet_entry.event_id})
    assert r.status_code == 200


def test_meet_entry_patch_missing(client):
    assert client.patch("/meet_entries/999", json={"event_id": 1}).status_code == 404


@pytest.mark.parametrize("field, label", [
    ("swimmer_id", "Swimmer"), ("meet_id", "Meet"), ("event_id", "Event"),
])
def test_meet_entry_patch_missing_fk(client, meet_entry, field, label):
    r = client.patch(f"/meet_entries/{meet_entry.id}", json={field: 999})
    assert r.status_code == 404
    assert r.json()["detail"] == f"{label} 999 not found"


def test_meet_entry_patch_would_duplicate(client, meet_entry, meet, swimmer):
    event2 = client.post("/events/", json={"distance": 100, "stroke": "FR", "course": "SCY"}).json()
    other = client.post(
        "/meet_entries/", json={"meet_id": meet.id, "swimmer_id": swimmer.id, "event_id": event2["id"]}
    ).json()
    r = client.patch(f"/meet_entries/{other['id']}", json={"event_id": meet_entry.event_id})
    assert r.status_code == 400


def test_meet_entry_patch_rejects_null(client, meet_entry):
    assert client.patch(f"/meet_entries/{meet_entry.id}", json={"meet_id": None}).status_code == 422


# --- swim times ------------------------------------------------------------

def test_swim_time_create_list_patch(client, meet_entry):
    r = client.post("/swim_times/", json={"meet_entry_id": meet_entry.id, "time_seconds": 32.45})
    assert r.status_code == 200
    st = r.json()
    assert st["time_seconds"] == 32.45

    assert len(client.get("/swim_times/").json()) == 1
    assert len(client.get("/swim_times/", params={"meet_entry_id": meet_entry.id}).json()) == 1
    assert client.get("/swim_times/", params={"meet_entry_id": 999}).json() == []

    r = client.patch(f"/swim_times/{st['id']}", json={"time_seconds": 31.0})
    assert r.json()["time_seconds"] == 31.0


def test_swim_time_duplicate_points_to_patch(client, meet_entry):
    payload = {"meet_entry_id": meet_entry.id, "time_seconds": 32.45}
    first = client.post("/swim_times/", json=payload).json()
    r = client.post("/swim_times/", json=payload)
    assert r.status_code == 400
    assert f"PATCH /swim_times/{first['id']}" in r.json()["detail"]


def test_swim_time_missing_entry(client):
    r = client.post("/swim_times/", json={"meet_entry_id": 999, "time_seconds": 30.0})
    assert r.status_code == 404


def test_swim_time_patch_missing(client):
    assert client.patch("/swim_times/999", json={"time_seconds": 30.0}).status_code == 404


@pytest.mark.parametrize("payload", [{"time_seconds": 0}, {"time_seconds": -1}, {"time_seconds": None}])
def test_swim_time_patch_validation(client, meet_entry, payload):
    st = client.post("/swim_times/", json={"meet_entry_id": meet_entry.id, "time_seconds": 30.0}).json()
    assert client.patch(f"/swim_times/{st['id']}", json=payload).status_code == 422


# --- time standards --------------------------------------------------------

def _standard(event_id, **overrides):
    return {
        "event_id": event_id, "organization": "USA Swimming", "age_group": "11-12",
        "gender": "F", "standard_name": "BB", "standard_rank": 2,
        "time_seconds": 29.99, "season": "2024-2028", **overrides,
    }


def test_time_standard_create_and_duplicate(client, swim_event):
    r = client.post("/time_standards/", json=_standard(swim_event.id))
    assert r.status_code == 200
    assert client.post("/time_standards/", json=_standard(swim_event.id)).status_code == 400
    # differing on any key field is not a duplicate
    assert client.post("/time_standards/", json=_standard(swim_event.id, gender="M")).status_code == 200


def test_time_standard_missing_event(client):
    assert client.post("/time_standards/", json=_standard(999)).status_code == 404


def test_time_standard_list_filters(client, swim_event):
    client.post("/time_standards/", json=_standard(swim_event.id))
    client.post("/time_standards/", json=_standard(
        swim_event.id, organization="MN Swimming", age_group="13-14", gender="M",
        standard_name="GOLD", season="2025-2026",
    ))

    def count(**params):
        return len(client.get("/time_standards/", params=params).json())

    assert count() == 2
    assert count(event_id=swim_event.id) == 2
    assert count(organization="MN Swimming") == 1
    assert count(age_group="11-12") == 1
    assert count(gender="M") == 1
    assert count(season="2024-2028") == 1
    assert count(organization="USA Swimming", gender="M") == 0
