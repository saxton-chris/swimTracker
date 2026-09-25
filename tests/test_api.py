import pytest


def test_root_serves_frontend(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "/static/main.js" in r.text


@pytest.mark.parametrize("path", ["/static/main.js", "/static/views/entries.js", "/static/styles.css"])
def test_static_assets_served(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/static/main.js", "/static/views/entries.js"])
def test_js_modules_are_served_as_javascript(client, path):
    # Browsers won't run an ES module served as anything else (e.g. text/plain).
    assert client.get(path).headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("path", ["/", "/static/main.js", "/static/views/entries.js", "/static/styles.css"])
def test_frontend_is_revalidated_on_every_load(client, path):
    assert client.get(path).headers["cache-control"] == "no-cache"


def test_api_responses_have_no_cache_header(client):
    assert "cache-control" not in client.get("/health").headers


def test_health(client):
    assert client.get("/health").json() == {"status": "running"}


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


def test_meet_end_date_defaults_to_none(client):
    r = client.post("/meets/", json={"name": "One day", "date": "2026-01-10"})
    assert r.json()["end_date"] is None


@pytest.mark.parametrize("end", ["2026-01-10", "2026-01-12"])  # same day, or later
def test_meet_create_with_end_date(client, end):
    r = client.post("/meets/", json={"name": "Invite", "date": "2026-01-10", "end_date": end})
    assert r.status_code == 200
    assert r.json()["end_date"] == end


def test_meet_create_rejects_end_before_start(client):
    r = client.post("/meets/", json={"name": "Invite", "date": "2026-01-10", "end_date": "2026-01-09"})
    assert r.status_code == 422
    assert "end_date must be on or after date" in r.text


def test_meet_patch_end_date(client, meet):  # meet fixture: 2026-01-10, no end date
    r = client.patch(f"/meets/{meet.id}", json={"end_date": "2026-01-12"})
    assert r.status_code == 200 and r.json()["end_date"] == "2026-01-12"

    r = client.patch(f"/meets/{meet.id}", json={"end_date": None})  # back to a one-day meet
    assert r.status_code == 200 and r.json()["end_date"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"end_date": "2026-01-09"},  # end before the stored start
        {"date": "2026-01-13"},  # start moved past the stored end
        {"date": "2026-01-20", "end_date": "2026-01-15"},  # both sent, still reversed
    ],
)
def test_meet_patch_rejects_reversed_range(client, meet, payload):
    client.patch(f"/meets/{meet.id}", json={"end_date": "2026-01-12"})
    r = client.patch(f"/meets/{meet.id}", json=payload)
    assert r.status_code == 422
    assert r.json()["detail"] == "end_date must be on or after date"
    stored = client.get("/meets/").json()[0]
    assert (stored["date"], stored["end_date"]) == ("2026-01-10", "2026-01-12")  # unchanged


def test_meet_patch_moves_whole_range(client, meet):
    client.patch(f"/meets/{meet.id}", json={"end_date": "2026-01-12"})
    r = client.patch(f"/meets/{meet.id}", json={"date": "2026-02-06", "end_date": "2026-02-08"})
    assert r.status_code == 200
    assert (r.json()["date"], r.json()["end_date"]) == ("2026-02-06", "2026-02-08")


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


@pytest.mark.parametrize(
    "payload",
    [
        {"distance": 0, "stroke": "FR", "course": "SCY"},
        {"distance": 50, "stroke": "XX", "course": "SCY"},
        {"distance": 50, "stroke": "FR", "course": "YDS"},
    ],
)
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


@pytest.mark.parametrize(
    "bad_field, label",
    [
        ("swimmer_id", "Swimmer"),
        ("meet_id", "Meet"),
        ("event_id", "Event"),
    ],
)
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


@pytest.mark.parametrize(
    "field, label",
    [
        ("swimmer_id", "Swimmer"),
        ("meet_id", "Meet"),
        ("event_id", "Event"),
    ],
)
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


@pytest.mark.parametrize(
    "payload",
    [
        {"time_seconds": 0},
        {"time_seconds": -1},
        {"time_seconds": None},  # a result needs a time unless it's a DQ
        {"dq": None},
        {"dq_reason": "False start"},  # a reason without a DQ
        {"relay_leg": 2},  # relay fields on an individual event
        {"split_seconds": 15.0},
    ],
)
def test_swim_time_patch_validation(client, meet_entry, payload):
    st = client.post("/swim_times/", json={"meet_entry_id": meet_entry.id, "time_seconds": 30.0}).json()
    assert client.patch(f"/swim_times/{st['id']}", json=payload).status_code == 422


# --- DQs and relays ----------------------------------------------------------


def test_dq_without_a_time(client, meet_entry):
    r = client.post("/swim_times/", json={"meet_entry_id": meet_entry.id, "dq": True, "dq_reason": " False start "})
    assert r.status_code == 200
    st = r.json()
    assert (st["dq"], st["dq_reason"], st["time_seconds"]) == (True, "False start", None)


def test_dq_can_keep_the_time_swum(client, meet_entry):
    r = client.post("/swim_times/", json={"meet_entry_id": meet_entry.id, "dq": True, "time_seconds": 42.96})
    assert r.json()["time_seconds"] == 42.96


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "time_seconds is required unless the swim is a DQ"),
        ({"time_seconds": 30.0, "dq_reason": "Other"}, "dq_reason is only allowed on a DQ"),
        ({"dq": True, "relay_leg": 5}, "less than or equal to 4"),
    ],
)
def test_result_validation_on_create(client, meet_entry, payload, message):
    r = client.post("/swim_times/", json={"meet_entry_id": meet_entry.id, **payload})
    assert r.status_code == 422
    assert message in r.text


def test_relay_fields_only_on_relay_events(client, meet_entry):
    r = client.post("/swim_times/", json={"meet_entry_id": meet_entry.id, "time_seconds": 30.0, "relay_leg": 1})
    assert r.status_code == 422
    assert "only for relays, not 50 FR SCY" in r.json()["detail"]


@pytest.fixture
def relay_entry(client, swimmer, meet):
    event = client.post("/events/", json={"distance": 200, "stroke": "IM", "course": "LCM", "relay": True}).json()
    body = {"meet_id": meet.id, "swimmer_id": swimmer.id, "event_id": event["id"]}
    return client.post("/meet_entries/", json=body).json()


def test_relay_result_with_leg_and_split(client, relay_entry):
    body = {"meet_entry_id": relay_entry["id"], "time_seconds": 184.99, "relay_leg": 4, "split_seconds": 41.94}
    st = client.post("/swim_times/", json=body).json()
    assert (st["time_seconds"], st["relay_leg"], st["split_seconds"]) == (184.99, 4, 41.94)


def test_relay_and_individual_events_are_distinct(client, swim_event):
    r = client.post("/events/", json={"distance": 50, "stroke": "FR", "course": "SCY", "relay": True})
    assert r.status_code == 200
    assert r.json()["name"] == "50 FR-R SCY"
    names = sorted(e["name"] for e in client.get("/events/").json())
    assert names == ["50 FR SCY", "50 FR-R SCY"]
    dup = client.post("/events/", json={"distance": 50, "stroke": "FR", "course": "SCY", "relay": True})
    assert dup.status_code == 400
    assert "50 FR-R SCY" in dup.json()["detail"]


def test_medley_relay_name(client):
    r = client.post("/events/", json={"distance": 200, "stroke": "IM", "course": "SCY", "relay": True})
    assert r.json()["name"] == "200 MED-R SCY"


def test_patch_to_dq_then_back(client, meet_entry):
    st = client.post("/swim_times/", json={"meet_entry_id": meet_entry.id, "time_seconds": 30.0}).json()
    url = f"/swim_times/{st['id']}"

    dq = client.patch(url, json={"dq": True, "dq_reason": "Scissors kick", "time_seconds": None}).json()
    assert (dq["dq"], dq["dq_reason"], dq["time_seconds"]) == (True, "Scissors kick", None)

    # Un-DQ'ing needs a time again, and drops the reason automatically.
    assert client.patch(url, json={"dq": False}).status_code == 422
    back = client.patch(url, json={"dq": False, "time_seconds": 31.5}).json()
    assert (back["dq"], back["dq_reason"], back["time_seconds"]) == (False, None, 31.5)


# --- time standards --------------------------------------------------------


def _standard(event_id, **overrides):
    return {
        "event_id": event_id,
        "organization": "USA Swimming",
        "age_group": "11-12",
        "gender": "F",
        "standard_name": "BB",
        "standard_rank": 2,
        "time_seconds": 29.99,
        "season": "2024-2028",
        **overrides,
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
    client.post(
        "/time_standards/",
        json=_standard(
            swim_event.id,
            organization="MN Swimming",
            age_group="13-14",
            gender="M",
            standard_name="GOLD",
            season="2025-2026",
        ),
    )

    def count(**params):
        return len(client.get("/time_standards/", params=params).json())

    assert count() == 2
    assert count(event_id=swim_event.id) == 2
    assert count(organization="MN Swimming") == 1
    assert count(age_group="11-12") == 1
    assert count(gender="M") == 1
    assert count(season="2024-2028") == 1
    assert count(organization="USA Swimming", gender="M") == 0


def test_time_standard_sets(client, swim_event):
    assert client.get("/time_standards/sets").json() == []
    for overrides in (
        {"organization": "USA Swimming", "season": "2024-2028"},
        {"organization": "USA Swimming", "season": "2024-2028", "gender": "M"},  # same set, listed once
        {"organization": "MN Swimming", "season": "2025-2026"},
        {"organization": "MN Swimming", "season": "2024-2025"},
    ):
        client.post("/time_standards/", json=_standard(swim_event.id, **overrides))

    assert client.get("/time_standards/sets").json() == [
        {"organization": "MN Swimming", "season": "2024-2025"},
        {"organization": "MN Swimming", "season": "2025-2026"},
        {"organization": "USA Swimming", "season": "2024-2028"},
    ]


# --- deletes ---------------------------------------------------------------


@pytest.mark.parametrize("path", ["/swimmers/999", "/meets/999", "/meet_entries/999", "/swim_times/999"])
def test_delete_missing(client, path):
    assert client.delete(path).status_code == 404


def _add_time(client, meet_entry_id, seconds=30.0):
    return client.post("/swim_times/", json={"meet_entry_id": meet_entry_id, "time_seconds": seconds}).json()


def test_swim_time_delete_keeps_entry(client, meet_entry):
    st = _add_time(client, meet_entry.id)
    assert client.delete(f"/swim_times/{st['id']}").status_code == 204
    assert client.get("/swim_times/").json() == []
    assert len(client.get("/meet_entries/").json()) == 1
    # entry can get a fresh time afterwards
    assert client.post("/swim_times/", json={"meet_entry_id": meet_entry.id, "time_seconds": 29.0}).status_code == 200


def test_meet_entry_delete_cascades_to_time(client, meet_entry):
    _add_time(client, meet_entry.id)
    assert client.delete(f"/meet_entries/{meet_entry.id}").status_code == 204
    assert client.get("/meet_entries/").json() == []
    assert client.get("/swim_times/").json() == []


@pytest.fixture
def two_entries(client, meet_entry, swimmer, meet, swim_event):
    """meet_entry plus a second entry sharing its meet but with another swimmer,
    and a third sharing its swimmer at another meet; all three have times."""
    other_swimmer = client.post("/swimmers/", json={"name": "B", "birthdate": "2013-01-01", "gender": "M"}).json()
    other_meet = client.post("/meets/", json={"name": "Other", "date": "2026-02-01"}).json()
    same_meet = client.post(
        "/meet_entries/", json={"meet_id": meet.id, "swimmer_id": other_swimmer["id"], "event_id": swim_event.id}
    ).json()
    same_swimmer = client.post(
        "/meet_entries/", json={"meet_id": other_meet["id"], "swimmer_id": swimmer.id, "event_id": swim_event.id}
    ).json()
    for entry_id in (meet_entry.id, same_meet["id"], same_swimmer["id"]):
        _add_time(client, entry_id)
    return same_meet, same_swimmer


def test_swimmer_delete_cascades(client, swimmer, two_entries):
    same_meet, _ = two_entries
    assert client.delete(f"/swimmers/{swimmer.id}").status_code == 204
    assert [e["id"] for e in client.get("/meet_entries/").json()] == [same_meet["id"]]
    assert [t["meet_entry_id"] for t in client.get("/swim_times/").json()] == [same_meet["id"]]
    assert len(client.get("/meets/").json()) == 2  # meets untouched


def test_meet_delete_cascades(client, meet, two_entries):
    _, same_swimmer = two_entries
    assert client.delete(f"/meets/{meet.id}").status_code == 204
    assert [e["id"] for e in client.get("/meet_entries/").json()] == [same_swimmer["id"]]
    assert [t["meet_entry_id"] for t in client.get("/swim_times/").json()] == [same_swimmer["id"]]
    assert len(client.get("/swimmers/").json()) == 2  # swimmers untouched
