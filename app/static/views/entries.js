// Entries & Results tab: meet entries grouped by meet, and the dialog that
// edits an entry and its result together.

import { api } from "../api.js";
import { groupToggle, hiddenCount, storedSet } from "../collapse.js";
import { setupDialog } from "../dialog.js";
import { actionButton, el, fillSelect } from "../dom.js";
import { ageAt, blankToNull, formatMeetDates, formatTime, parseTime } from "../format.js";
import { ageGroupFor, indexSet, loadSet, loadedSet, setKey, setLabel, standingFor } from "../standards-data.js";
import { STROKE_ORDER, byId, mutate, newestMeet, state } from "../store.js";
import { showView } from "../tabs.js";
import { toast } from "../toast.js";

const ENTRY_COLUMNS = 6;
const collapsedMeets = storedSet("swimTracker.collapsedMeets"); // meet ids

// ---------------------------------------------------------------------------
// "Compare to standard": which set the Standard column uses (remembered in this browser)
// ---------------------------------------------------------------------------

const STANDARD_PREF_KEY = "swimTracker.entriesStandard";
let chosenStandard = (() => {
  try {
    return localStorage.getItem(STANDARD_PREF_KEY) || "";
  } catch {
    return "";
  }
})();
const loadingStandards = new Set();

/** Fill the standard dropdown; returns the chosen set's key, or "" when none (or it no longer exists). */
function fillStandardSelect() {
  const select = document.getElementById("entries-standard");
  select.replaceChildren(
    el("option", { value: "", textContent: "No standard" }),
    ...state.standardSets.map((s) => el("option", { value: setKey(s), textContent: setLabel(s) })),
  );
  select.value = state.standardSets.some((s) => setKey(s) === chosenStandard) ? chosenStandard : "";
  return select.value;
}

/** The chosen set's lookup (see indexSet), fetching it first if needed (renders again once it arrives). */
function chosenStandardIndex(key) {
  if (!key) return null;
  if (loadedSet(key)) return indexSet(key);
  if (!loadingStandards.has(key)) {
    loadingStandards.add(key);
    const set = state.standardSets.find((s) => setKey(s) === key);
    loadSet(set)
      .catch((err) => {
        chosenStandard = ""; // for this page load only; the saved choice is kept for next time
        toast(`Couldn't load ${setLabel(set)}: ${err.message}`, true);
      })
      .finally(() => {
        loadingStandards.delete(key);
        renderEntries();
      });
  }
  return null;
}

document.getElementById("entries-standard").addEventListener("change", (ev) => {
  chosenStandard = ev.target.value;
  try {
    localStorage.setItem(STANDARD_PREF_KEY, chosenStandard);
  } catch {
    // storage unavailable: the choice still applies until the page reloads
  }
  renderEntries();
});

/**
 * The Standard cell: for a timed individual swim, the best tier reached in the chosen set (for the
 * swimmer's age on the meet's first day, gender, and the event), and how far off the next tier is.
 * Blank for relays, DQs, and swims without a time.
 */
function standingCell(standard, { event, swimmer, meet, time }) {
  const td = el("td", { class: "c-standing" });
  if (!standard || event.relay || !time || time.dq || time.time_seconds == null) return td;

  const age = ageAt(swimmer.birthdate, meet.date);
  const ageGroup = ageGroupFor(standard.ageGroups, age);
  const tiers = ageGroup ? standard.tiers.get(`${event.id}|${swimmer.gender}|${ageGroup}`) : null;
  if (!tiers) {
    td.title = ageGroup ? `No standard for ${event.name}, ${ageGroup}` : `No age group for age ${age}`;
    td.append(el("span", { class: "std-none", textContent: "—" }));
    return td;
  }

  const { achieved, next, toNext } = standingFor(time.time_seconds, tiers);
  td.title = `Age ${age} at this meet: ${ageGroup}`;
  td.append(
    achieved ? el("span", { class: "std-badge", textContent: achieved.name }) : "", // "x to B" says it all
    el("span", {
      class: "std-next",
      textContent: next ? `${formatTime(toNext)} to ${next.name} (${formatTime(next.seconds)})` : "Top standard",
    }),
  );
  return td;
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

export function renderEntries() {
  const meetFilter = document.getElementById("filter-meet");
  const swimmerFilter = document.getElementById("filter-swimmer");
  fillSelect(meetFilter, state.meets, (m) => `${m.name} (${m.date})`, { blank: "All meets" });
  fillSelect(swimmerFilter, state.swimmers, (s) => s.name, { blank: "All swimmers" });
  const standardKey = fillStandardSelect();
  const standard = chosenStandardIndex(standardKey);
  // The Standard column shows once a standard is chosen (its cells fill in when the set has loaded).
  document.getElementById("entries-table").classList.toggle("show-standing", Boolean(standardKey));

  const meets = byId(state.meets);
  const swimmers = byId(state.swimmers);
  const events = byId(state.events);
  const timeByEntry = new Map(state.times.map((t) => [t.meet_entry_id, t]));

  const meetId = Number(meetFilter.value) || null;
  const swimmerId = Number(swimmerFilter.value) || null;

  const rows = state.entries
    .filter((e) => (!meetId || e.meet_id === meetId) && (!swimmerId || e.swimmer_id === swimmerId))
    .map((e) => ({
      entry: e,
      meet: meets.get(e.meet_id),
      swimmer: swimmers.get(e.swimmer_id),
      event: events.get(e.event_id),
      time: timeByEntry.get(e.id),
    }))
    .sort((a, b) =>
      a.meet.date.localeCompare(b.meet.date) ||
      a.meet.name.localeCompare(b.meet.name) ||
      a.swimmer.name.localeCompare(b.swimmer.name) ||
      a.event.course.localeCompare(b.event.course) ||
      Number(a.event.relay) - Number(b.event.relay) || // relays after individual events
      STROKE_ORDER[a.event.stroke] - STROKE_ORDER[b.event.stroke] ||
      a.event.distance - b.event.distance
    );

  // Rows are sorted by meet, so each meet's entries sit under one heading row
  // (name and dates shown once) instead of repeating them in every row.
  const groups = [];
  for (const r of rows) {
    if (!groups.length || groups[groups.length - 1].meet !== r.meet) groups.push({ meet: r.meet, rows: [] });
    groups[groups.length - 1].rows.push(r);
  }
  const tableRows = [];
  for (const { meet, rows: meetRows } of groups) {
    const collapsed = collapsedMeets.has(meet.id);
    tableRows.push(meetHeading(meet, meetRows.length, collapsed));
    if (!collapsed) tableRows.push(...meetRows.map((r) => entryRow(r, standard)));
  }
  document.getElementById("entries-body").replaceChildren(...tableRows);

  const empty = document.getElementById("entries-empty");
  empty.hidden = rows.length > 0;
  empty.textContent = state.entries.length ? "No entries match these filters." : "No meet entries yet.";
}

function meetHeading(meet, entryCount, collapsed) {
  return el("tr", { class: collapsed ? "group-heading meet-heading collapsed" : "group-heading meet-heading" },
    // The " " text nodes keep the parts separate for screen readers and copy/paste; CSS sets the visual gap.
    el("th", { colSpan: ENTRY_COLUMNS, scope: "colgroup" },
      groupToggle({
        label: meet.name, labelClass: "meet-name", key: meet.id,
        collapsedSet: collapsedMeets, rerender: renderEntries, what: "results",
      }),
      " ",
      el("span", { class: "meet-dates", textContent: formatMeetDates(meet) }),
      meet.location ? " " : null,
      meet.location ? el("span", { class: "meet-location", textContent: meet.location }) : null,
      ...hiddenCount(collapsed, entryCount, "entry", "entries")));
}

/** "Leg 4 · split 41.94" for a relay result, or null. */
function relayDetail(time) {
  if (!time || (time.relay_leg == null && time.split_seconds == null)) return null;
  const parts = [];
  if (time.relay_leg != null) parts.push(`Leg ${time.relay_leg}`);
  if (time.split_seconds != null) parts.push(`split ${formatTime(time.split_seconds)}`);
  return parts.join(" · ");
}

function timeCell(time) {
  if (!time) return el("td", { class: "c-time pending", textContent: "—" });
  if (time.dq) {
    // A DQ'd swim's time (if the results printed one) isn't official, so it's shown small and muted.
    return el("td", { class: "c-time" },
      el("span", { class: "dq-badge", textContent: "DQ", title: time.dq_reason || "Disqualified" }),
      time.time_seconds != null ? el("span", { class: "dq-time", textContent: formatTime(time.time_seconds) }) : null);
  }
  return el("td", { class: "c-time" }, el("span", { class: "clock", textContent: formatTime(time.time_seconds) }));
}

function entryRow(row, standard) {
  const { entry, meet, swimmer, event, time } = row;
  const detail = relayDetail(time);
  const notes = [time && time.dq && time.dq_reason ? `DQ: ${time.dq_reason}` : null, time && time.notes]
    .filter(Boolean).join(" · ");
  return el("tr", { class: time && time.dq ? "entry dq" : "entry" },
    el("td", { class: "c-swimmer", textContent: swimmer.name }),
    el("td", { class: "c-event" },
      event.name,
      detail ? el("span", { class: "relay-detail", textContent: detail }) : null),
    timeCell(time),
    standingCell(standard, row),
    el("td", { class: "notes c-notes", textContent: notes }),
    el("td", { class: "actions" },
      actionButton(time ? "Edit" : "Add time", () => openEntryDialog(entry)),
      actionButton("Delete", () => deleteEntry(entry, swimmer, event, meet), true)),
  );
}

/** Show the Entries tab filtered to one meet and/or swimmer (used by the name links on other tabs). */
export function filterEntries({ meet = "", swimmer = "" }) {
  document.getElementById("filter-meet").value = String(meet);
  document.getElementById("filter-swimmer").value = String(swimmer);
  renderEntries();
  showView("entries");
}

document.getElementById("filter-meet").addEventListener("change", renderEntries);
document.getElementById("filter-swimmer").addEventListener("change", renderEntries);

// ---------------------------------------------------------------------------
// Entry + result dialog
// ---------------------------------------------------------------------------

let editingEntry = null;
let lastCourse = "SCY";

/** Find the event for distance/stroke/course/relay, creating it if it doesn't exist yet. */
async function resolveEventId(distance, stroke, course, relay) {
  const found = state.events.find((e) =>
    e.distance === distance && e.stroke === stroke && e.course === course && e.relay === relay);
  if (found) return found.id;
  const created = await api("POST", "/events/", { distance, stroke, course, relay });
  state.events.push(created);
  return created.id;
}

const RELAY_STROKES = new Set(["FR", "IM"]); // free relay, medley relay

/** Show the relay/DQ fields only when they apply, and relabel IM as "Medley" for relays. */
function syncEntryForm() {
  const form = document.getElementById("entry-form");
  const relay = form.elements.relay.checked;
  for (const option of form.elements.stroke.options) {
    option.disabled = relay && !RELAY_STROKES.has(option.value);
    option.textContent = relay && option.dataset.relayLabel ? option.dataset.relayLabel : option.dataset.label;
  }
  if (relay && !RELAY_STROKES.has(form.elements.stroke.value)) form.elements.stroke.value = "FR";
  document.getElementById("relay-fields").hidden = !relay;
  form.querySelector("[data-relay-text]").textContent = relay ? "Team time" : "Time";
  document.getElementById("dq-reason-field").hidden = !form.elements.dq.checked;
}

{
  const form = document.getElementById("entry-form");
  for (const option of form.elements.stroke.options) option.dataset.label = option.textContent;
  form.addEventListener("change", syncEntryForm);
}

const entryDialog = setupDialog("entry-dialog", async (f) => {
  // Validate everything before writing anything, so bad input can't leave a half-saved entry.
  const relay = f.relay === "on";
  const dq = f.dq === "on";
  const seconds = parseTime(f.time);
  const split = relay ? parseTime(f.split) : null;
  const leg = relay && f.relay_leg ? Number(f.relay_leg) : null;
  const timeNotes = blankToNull(f.time_notes);
  const dqReason = dq ? blankToNull(f.dq_reason) : null;
  const distance = Number(f.distance);
  if (!Number.isInteger(distance) || distance <= 0) throw new Error("Distance must be a positive whole number.");
  if (relay && !RELAY_STROKES.has(f.stroke)) throw new Error("A relay is Free or Medley.");
  const hasResult = seconds !== null || dq;
  if (!hasResult && (timeNotes || leg !== null || split !== null)) {
    throw new Error("Enter a time (or mark it a DQ) to save the result details.");
  }

  const eventId = await resolveEventId(distance, f.stroke, f.course, relay);
  lastCourse = f.course;
  const body = { meet_id: Number(f.meet_id), swimmer_id: Number(f.swimmer_id), event_id: eventId };

  const isNew = !editingEntry;
  const entry = isNew
    ? await api("POST", "/meet_entries/", body)
    : await api("PATCH", `/meet_entries/${editingEntry.id}`, body);
  // If the time step below fails, the dialog stays open; a retry must edit
  // the entry we just created rather than try to add it a second time.
  editingEntry = entry;

  const existing = state.times.find((t) => t.meet_entry_id === entry.id);
  const result = {
    time_seconds: seconds,
    notes: timeNotes,
    dq,
    dq_reason: dqReason,
    relay_leg: leg,
    split_seconds: split,
  };
  if (!hasResult && existing) {
    await api("DELETE", `/swim_times/${existing.id}`);
  } else if (hasResult && existing) {
    await api("PATCH", `/swim_times/${existing.id}`, result);
  } else if (hasResult) {
    await api("POST", "/swim_times/", { meet_entry_id: entry.id, ...result });
  }
  toast(isNew ? "Entry added" : "Entry updated");
});

function openEntryDialog(entry = null) {
  if (!state.meets.length || !state.swimmers.length) {
    toast("Add at least one swimmer and one meet first.", true);
    return;
  }
  editingEntry = entry;
  const form = document.getElementById("entry-form");
  fillSelect(form.elements.meet_id, state.meets, (m) => `${m.name} (${m.date})`);
  fillSelect(form.elements.swimmer_id, state.swimmers, (s) => s.name);

  let values;
  if (entry) {
    const event = state.events.find((e) => e.id === entry.event_id);
    const time = state.times.find((t) => t.meet_entry_id === entry.id);
    values = {
      meet_id: entry.meet_id,
      swimmer_id: entry.swimmer_id,
      distance: event.distance,
      stroke: event.stroke,
      course: event.course,
      relay: event.relay,
      time: time && time.time_seconds != null ? formatTime(time.time_seconds) : "",
      time_notes: time ? time.notes : "",
      dq: time ? time.dq : false,
      dq_reason: time ? time.dq_reason : "",
      relay_leg: time && time.relay_leg != null ? String(time.relay_leg) : "",
      split: time && time.split_seconds != null ? formatTime(time.split_seconds) : "",
    };
  } else {
    // Default to whatever the Entries tab is filtered to.
    values = {
      meet_id: document.getElementById("filter-meet").value || newestMeet().id,
      swimmer_id: document.getElementById("filter-swimmer").value || state.swimmers[0].id,
      distance: 50,
      stroke: "FR",
      course: lastCourse,
    };
  }
  entryDialog.open(entry ? "Edit entry" : "Add entry", values);
}

async function deleteEntry(entry, swimmer, event, meet) {
  const hasTime = state.times.some((t) => t.meet_entry_id === entry.id);
  const msg = `Delete ${swimmer.name}'s ${event.name} entry at ${meet.name}?` +
    (hasTime ? "\n\nIts recorded time will also be deleted." : "");
  if (!confirm(msg)) return;
  await mutate(() => api("DELETE", `/meet_entries/${entry.id}`), "Entry deleted");
}

document.getElementById("add-entry").addEventListener("click", () => openEntryDialog());
