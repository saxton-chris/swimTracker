"use strict";

// ---------------------------------------------------------------------------
// State: the whole dataset is small, so we load every list up front and
// reload after each change instead of patching local copies.
// ---------------------------------------------------------------------------

const state = {
  swimmers: [],
  meets: [],
  events: [],
  entries: [],
  times: [],
};

const byId = (list) => new Map(list.map((x) => [x.id, x]));
const STROKE_ORDER = { FR: 0, BK: 1, BR: 2, FL: 3, IM: 4 };
let lastCourse = "SCY";

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(data, res));
  return data;
}

function errorMessage(data, res) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors
    return detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  return `${res.status} ${res.statusText}`;
}

async function loadAll() {
  const [swimmers, meets, events, entries, times] = await Promise.all([
    api("GET", "/swimmers/"),
    api("GET", "/meets/"),
    api("GET", "/events/"),
    api("GET", "/meet_entries/"),
    api("GET", "/swim_times/"),
  ]);
  Object.assign(state, { swimmers, meets, events, entries, times });
  state.swimmers.sort((a, b) => a.name.localeCompare(b.name));
  state.meets.sort((a, b) => b.date.localeCompare(a.date) || a.name.localeCompare(b.name));
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/** 62.45 -> "1:02.45", 32.4 -> "32.40" */
function formatTime(seconds) {
  const hundredths = Math.round(seconds * 100);
  const mins = Math.floor(hundredths / 6000);
  const rest = ((hundredths % 6000) / 100).toFixed(2);
  return mins ? `${mins}:${rest.padStart(5, "0")}` : rest;
}

/** "1:02.45" or "62.45" -> 62.45. Returns null for blank, throws on garbage. */
function parseTime(text) {
  const s = text.trim();
  if (!s) return null;
  const m = s.match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  if (!m) throw new Error(`"${s}" isn't a valid time. Use seconds (32.45) or m:ss.xx (1:02.45).`);
  const mins = m[1] ? Number(m[1]) : 0;
  const secs = Number(m[2]);
  if (m[1] && secs >= 60) throw new Error(`"${s}": seconds must be under 60 when minutes are given.`);
  const total = mins * 60 + secs;
  if (total <= 0) throw new Error("Time must be greater than zero.");
  return Math.round(total * 100) / 100;
}

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" });

/** ISO "2026-01-10" -> Date at local midnight (new Date(iso) would be UTC midnight, i.e. the day before in the Americas). */
function localDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** ISO "2026-01-10" -> "Jan 10, 2026" */
function formatDate(iso) {
  return DATE_FORMAT.format(localDate(iso));
}

/** A meet's dates: "Jan 10, 2026" for one day, "Jan 9 – 11, 2026" for a multi-day meet. */
function formatMeetDates(meet) {
  if (!meet.end_date || meet.end_date === meet.date) return formatDate(meet.date);
  return DATE_FORMAT.formatRange(localDate(meet.date), localDate(meet.end_date));
}

function ageOn(birthIso, onDate = new Date()) {
  const [y, m, d] = birthIso.split("-").map(Number);
  let age = onDate.getFullYear() - y;
  if (onDate.getMonth() + 1 < m || (onDate.getMonth() + 1 === m && onDate.getDate() < d)) age--;
  return age;
}

// ---------------------------------------------------------------------------
// DOM helpers (textContent everywhere, so user data is never parsed as HTML)
// ---------------------------------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node[k] = v;
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

const actionButton = (label, onClick, danger = false) =>
  el("button", { type: "button", class: danger ? "link danger" : "link", textContent: label, onclick: onClick });

/** A swimmer/meet name that filters the Entries tab when clicked. */
const nameButton = (label, onClick) =>
  el("button", { type: "button", class: "link name", textContent: label, onclick: onClick });

function fillSelect(select, items, labelFn, { blank } = {}) {
  const current = select.value;
  select.replaceChildren();
  if (blank !== undefined) select.append(el("option", { value: "", textContent: blank }));
  for (const item of items) select.append(el("option", { value: String(item.id), textContent: labelFn(item) }));
  if ([...select.options].some((o) => o.value === current)) select.value = current;
}

let toastTimer;
function toast(message, isError = false) {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.className = isError ? "toast error" : "toast";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), isError ? 6000 : 2500);
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

const VIEWS = ["entries", "swimmers", "meets"];

function showView(name) {
  if (!VIEWS.includes(name)) name = "entries";
  for (const v of VIEWS) document.getElementById(`view-${v}`).hidden = v !== name;
  for (const tab of document.querySelectorAll(".tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === name));
  }
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
}

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => showView(tab.dataset.view))
);

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function render() {
  renderSwimmers();
  renderMeets();
  renderEntries();
}

function renderSwimmers() {
  const body = document.getElementById("swimmers-body");
  body.replaceChildren(
    ...state.swimmers.map((s) =>
      el("tr", {},
        el("td", {}, nameButton(s.name, () => filterEntries({ swimmer: s.id }))),
        el("td", { class: "c-birthdate", textContent: formatDate(s.birthdate) }),
        el("td", { class: "num", textContent: ageOn(s.birthdate) }),
        el("td", { textContent: s.gender }),
        el("td", { class: "notes c-notes", textContent: s.notes || "" }),
        el("td", { class: "actions" },
          actionButton("Edit", () => openSwimmerDialog(s)),
          actionButton("Delete", () => deleteSwimmer(s), true)),
      )
    )
  );
  document.getElementById("swimmers-empty").hidden = state.swimmers.length > 0;
}

function renderMeets() {
  const counts = new Map();
  for (const e of state.entries) counts.set(e.meet_id, (counts.get(e.meet_id) || 0) + 1);

  const body = document.getElementById("meets-body");
  body.replaceChildren(
    ...state.meets.map((m) =>
      el("tr", {},
        el("td", { textContent: formatMeetDates(m) }),
        el("td", { class: "c-name" }, nameButton(m.name, () => filterEntries({ meet: m.id }))),
        el("td", { class: "c-location", textContent: m.location || "" }),
        el("td", { class: "num", textContent: counts.get(m.id) || 0 }),
        el("td", { class: "actions" },
          actionButton("Edit", () => openMeetDialog(m)),
          actionButton("Delete", () => deleteMeet(m), true)),
      )
    )
  );
  document.getElementById("meets-empty").hidden = state.meets.length > 0;
}

function renderEntries() {
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
      b.meet.date.localeCompare(a.meet.date) ||
      a.meet.name.localeCompare(b.meet.name) ||
      a.swimmer.name.localeCompare(b.swimmer.name) ||
      a.event.course.localeCompare(b.event.course) ||
      STROKE_ORDER[a.event.stroke] - STROKE_ORDER[b.event.stroke] ||
      a.event.distance - b.event.distance
    );

  document.getElementById("entries-body").replaceChildren(
    ...rows.map(({ entry, meet, swimmer, event, time }) =>
      el("tr", {},
        el("td", { class: "c-meet", textContent: meet.name }),
        el("td", { class: "c-date", textContent: formatMeetDates(meet) }),
        el("td", { class: "c-swimmer", textContent: swimmer.name }),
        el("td", { class: "c-event", textContent: event.name }),
        time
          ? el("td", { class: "num c-time" }, el("span", { class: "clock", textContent: formatTime(time.time_seconds) }))
          : el("td", { class: "num c-time pending", textContent: "—" }),
        el("td", { class: "notes c-notes", textContent: (time && time.notes) || "" }),
        el("td", { class: "actions" },
          actionButton(time ? "Edit" : "Add time", () => openEntryDialog(entry)),
          actionButton("Delete", () => deleteEntry(entry, swimmer, event, meet), true)),
      )
    )
  );

  const empty = document.getElementById("entries-empty");
  empty.hidden = rows.length > 0;
  empty.textContent = state.entries.length ? "No entries match these filters." : "No meet entries yet.";
}

function filterEntries({ meet = "", swimmer = "" }) {
  document.getElementById("filter-meet").value = String(meet);
  document.getElementById("filter-swimmer").value = String(swimmer);
  renderEntries();
  showView("entries");
}

document.getElementById("filter-meet").addEventListener("change", renderEntries);
document.getElementById("filter-swimmer").addEventListener("change", renderEntries);

// ---------------------------------------------------------------------------
// Dialog plumbing
// ---------------------------------------------------------------------------

/**
 * Wires a <dialog> form: cancel closes it, submit runs `onSave(formData)`.
 * If onSave throws, the error is shown inside the dialog and it stays open.
 */
function setupDialog(dialogId, onSave) {
  const dialog = document.getElementById(dialogId);
  const form = dialog.querySelector("form");
  const error = form.querySelector(".form-error");
  const submit = form.querySelector('button[type="submit"]');

  form.querySelector(".cancel").addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    error.hidden = true;
    submit.disabled = true;
    try {
      await onSave(Object.fromEntries(new FormData(form)));
      dialog.close();
      await refresh();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });

  return {
    open(title, values) {
      form.reset();
      error.hidden = true;
      form.querySelector("h2").textContent = title;
      for (const [name, value] of Object.entries(values)) {
        if (form.elements[name]) form.elements[name].value = value ?? "";
      }
      dialog.showModal();
    },
  };
}

const blankToNull = (s) => (s && s.trim() ? s.trim() : null);

// ---------------------------------------------------------------------------
// Swimmers
// ---------------------------------------------------------------------------

let editingSwimmer = null;
const swimmerDialog = setupDialog("swimmer-dialog", async (f) => {
  const body = { name: f.name.trim(), birthdate: f.birthdate, gender: f.gender, notes: blankToNull(f.notes) };
  if (editingSwimmer) await api("PATCH", `/swimmers/${editingSwimmer.id}`, body);
  else await api("POST", "/swimmers/", body);
  toast(editingSwimmer ? "Swimmer updated" : "Swimmer added");
});

function openSwimmerDialog(swimmer = null) {
  editingSwimmer = swimmer;
  swimmerDialog.open(swimmer ? "Edit swimmer" : "Add swimmer", swimmer || { gender: "F" });
}

async function deleteSwimmer(s) {
  const entries = state.entries.filter((e) => e.swimmer_id === s.id);
  if (!confirm(`Delete ${s.name}?${cascadeWarning(entries)}`)) return;
  await mutate(() => api("DELETE", `/swimmers/${s.id}`), "Swimmer deleted");
}

document.getElementById("add-swimmer").addEventListener("click", () => openSwimmerDialog());

// ---------------------------------------------------------------------------
// Meets
// ---------------------------------------------------------------------------

let editingMeet = null;
const meetDialog = setupDialog("meet-dialog", async (f) => {
  const endDate = blankToNull(f.end_date);
  if (endDate && endDate < f.date) throw new Error("End date must be on or after the start date.");
  const body = { name: f.name.trim(), date: f.date, end_date: endDate, location: blankToNull(f.location) };
  if (editingMeet) await api("PATCH", `/meets/${editingMeet.id}`, body);
  else await api("POST", "/meets/", body);
  toast(editingMeet ? "Meet updated" : "Meet added");
});

function openMeetDialog(meet = null) {
  editingMeet = meet;
  meetDialog.open(meet ? "Edit meet" : "Add meet", meet || {});
}

async function deleteMeet(m) {
  const entries = state.entries.filter((e) => e.meet_id === m.id);
  if (!confirm(`Delete meet "${m.name}"?${cascadeWarning(entries)}`)) return;
  await mutate(() => api("DELETE", `/meets/${m.id}`), "Meet deleted");
}

document.getElementById("add-meet").addEventListener("click", () => openMeetDialog());

/** "\n\nThis will also delete 3 meet entries and 2 results." for the confirm prompt. */
function cascadeWarning(entries) {
  if (!entries.length) return "";
  const ids = new Set(entries.map((e) => e.id));
  const results = state.times.filter((t) => ids.has(t.meet_entry_id)).length;
  const entryText = entries.length === 1 ? "1 meet entry" : `${entries.length} meet entries`;
  const resultText = results === 1 ? "1 result" : `${results} results`;
  return `\n\nThis will also delete ${entryText}` + (results ? ` and ${resultText}.` : ".");
}

// ---------------------------------------------------------------------------
// Meet entries + results (edited together in one dialog)
// ---------------------------------------------------------------------------

let editingEntry = null;

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
      meet_id: document.getElementById("filter-meet").value || state.meets[0].id,
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

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function mutate(fn, successMessage) {
  try {
    await fn();
    toast(successMessage);
  } catch (err) {
    toast(err.message, true);
  }
  await refresh();
}

async function refresh() {
  try {
    await loadAll();
    render();
  } catch (err) {
    toast(`Couldn't load data: ${err.message}`, true);
  }
}

showView(location.hash.slice(1));
refresh();
