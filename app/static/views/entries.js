// Entries & Results tab: meet entries grouped by meet, and the dialog that
// edits an entry and its result together.

import { api } from "../api.js";
import { groupToggle, hiddenCount, storedSet } from "../collapse.js";
import { setupDialog } from "../dialog.js";
import { actionButton, el, fillSelect } from "../dom.js";
import { blankToNull, formatMeetDates, formatTime, parseTime } from "../format.js";
import { STROKE_ORDER, byId, mutate, newestMeet, state } from "../store.js";
import { showView } from "../tabs.js";
import { toast } from "../toast.js";

const ENTRY_COLUMNS = 5;
const collapsedMeets = storedSet("swimTracker.collapsedMeets"); // meet ids

export function renderEntries() {
  const meetFilter = document.getElementById("filter-meet");
  const swimmerFilter = document.getElementById("filter-swimmer");
  fillSelect(meetFilter, state.meets, (m) => `${m.name} (${m.date})`, { blank: "All meets" });
  fillSelect(swimmerFilter, state.swimmers, (s) => s.name, { blank: "All swimmers" });

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
    if (!collapsed) tableRows.push(...meetRows.map(entryRow));
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

function entryRow({ entry, meet, swimmer, event, time }) {
  return el("tr", { class: "entry" },
    el("td", { class: "c-swimmer", textContent: swimmer.name }),
    el("td", { class: "c-event", textContent: event.name }),
    time
      ? el("td", { class: "c-time" }, el("span", { class: "clock", textContent: formatTime(time.time_seconds) }))
      : el("td", { class: "c-time pending", textContent: "—" }),
    el("td", { class: "notes c-notes", textContent: (time && time.notes) || "" }),
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

/** Find the event for distance/stroke/course, creating it if it doesn't exist yet. */
async function resolveEventId(distance, stroke, course) {
  const found = state.events.find((e) => e.distance === distance && e.stroke === stroke && e.course === course);
  if (found) return found.id;
  const created = await api("POST", "/events/", { distance, stroke, course });
  state.events.push(created);
  return created.id;
}

const entryDialog = setupDialog("entry-dialog", async (f) => {
  // Validate the time before writing anything, so a bad time can't leave a half-saved entry.
  const seconds = parseTime(f.time);
  const timeNotes = blankToNull(f.time_notes);
  const distance = Number(f.distance);
  if (!Number.isInteger(distance) || distance <= 0) throw new Error("Distance must be a positive whole number.");
  if (seconds === null && timeNotes) throw new Error("Enter a time to save result notes.");

  const eventId = await resolveEventId(distance, f.stroke, f.course);
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
  if (seconds === null && existing) {
    await api("DELETE", `/swim_times/${existing.id}`);
  } else if (seconds !== null && existing) {
    await api("PATCH", `/swim_times/${existing.id}`, { time_seconds: seconds, notes: timeNotes });
  } else if (seconds !== null) {
    await api("POST", "/swim_times/", { meet_entry_id: entry.id, time_seconds: seconds, notes: timeNotes });
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
      time: time ? formatTime(time.time_seconds) : "",
      time_notes: time ? time.notes : "",
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
