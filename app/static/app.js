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
  standardSets: [], // [{organization, season}] that have standards loaded
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

/** POST a file as the raw request body (e.g. a results PDF) and return the JSON reply. */
async function upload(path, file) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/pdf" }, body: file });
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
  const [swimmers, meets, events, entries, times, standardSets] = await Promise.all([
    api("GET", "/swimmers/"),
    api("GET", "/meets/"),
    api("GET", "/events/"),
    api("GET", "/meet_entries/"),
    api("GET", "/swim_times/"),
    api("GET", "/time_standards/sets"),
  ]);
  Object.assign(state, { swimmers, meets, events, entries, times, standardSets });
  state.swimmers.sort((a, b) => a.name.localeCompare(b.name));
  // Oldest first by start date, everywhere meets are listed.
  state.meets.sort((a, b) => a.date.localeCompare(b.date) || a.name.localeCompare(b.name));
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
function toast(message, isError = false, ms = isError ? 6000 : 2500) {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.className = isError ? "toast error" : "toast";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

const VIEWS = ["entries", "swimmers", "meets", "standards"];

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
  renderStandards();
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

const ENTRY_COLUMNS = 5;

// ---------------------------------------------------------------------------
// Collapsible groups (meets on Entries, age groups on Time Standards)
// ---------------------------------------------------------------------------

/**
 * A Set of collapsed group keys, kept in this browser only (a display
 * preference, not data). Storage is optional: without it nothing is remembered.
 */
function storedSet(storageKey) {
  let set;
  try {
    set = new Set(JSON.parse(localStorage.getItem(storageKey)) || []);
  } catch {
    set = new Set();
  }
  set.toggle = (key) => {
    if (set.has(key)) set.delete(key);
    else set.add(key);
    try {
      localStorage.setItem(storageKey, JSON.stringify([...set]));
    } catch {
      // storage unavailable: the choice still applies until the page reloads
    }
  };
  return set;
}

const collapsedMeets = storedSet("swimTracker.collapsedMeets");
const collapsedAgeGroups = storedSet("swimTracker.collapsedAgeGroups"); // "org|season|age group"

/**
 * The disclosure button at the start of a group heading row. Clicking it flips
 * `key` in `collapsedSet` and calls `rerender`, then puts focus back on the new
 * button (re-rendering replaces it) so keyboard users don't lose their place.
 */
function groupToggle({ label, labelClass, key, collapsedSet, rerender, what }) {
  const collapsed = collapsedSet.has(key);
  const toggle = el("button", {
    type: "button",
    class: "group-toggle",
    title: collapsed ? `Show ${what}` : `Hide ${what}`,
    onclick: () => {
      collapsedSet.toggle(key);
      rerender();
      document.querySelector(`.group-toggle[data-group="${CSS.escape(String(key))}"]`)?.focus();
    },
  }, el("span", { class: labelClass, textContent: label }));
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.dataset.group = String(key);
  return toggle;
}

/** " 4 entries hidden" for a collapsed heading, or nothing. */
const hiddenCount = (collapsed, n, one, many) =>
  collapsed ? [" ", el("span", { class: "group-count", textContent: `${plural(n, one, many)} hidden` })] : [];

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

/** Default meet for a new entry or import: the most recent one (meets are listed oldest first). */
const newestMeet = () => state.meets[state.meets.length - 1];

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

// ---------------------------------------------------------------------------
// Importing a meet results PDF
// ---------------------------------------------------------------------------

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** One-line summary of a POST /meets/{id}/import-results reply. */
function importSummary(r) {
  if (!r.results_parsed) return "No individual results found in that PDF.";
  const matched = r.times_imported + r.times_already_existed;
  if (!matched) return "No results in that PDF matched a swimmer on the Swimmers tab.";
  const parts = [];
  if (r.times_imported) {
    parts.push(`Imported ${plural(r.times_imported, "time", "times")}` +
      (r.meet_entries_created ? ` (${plural(r.meet_entries_created, "new entry", "new entries")})` : "") + ".");
  }
  if (r.times_already_existed) {
    parts.push(`${plural(r.times_already_existed, "result was", "results were")} already recorded.`);
  }
  return parts.join(" ");
}

const importDialog = setupDialog("import-dialog", async (f) => {
  if (!f.pdf || !f.pdf.size) throw new Error("Choose a results PDF to import.");
  const meetId = Number(f.meet_id);
  const result = await upload(`/meets/${meetId}/import-results`, f.pdf);
  // Show the meet that was just imported into.
  document.getElementById("filter-meet").value = String(meetId);
  document.getElementById("filter-swimmer").value = "";
  toast(importSummary(result), false, 6000);
});

function openImportDialog() {
  if (!state.meets.length) {
    toast("Add the meet on the Meets tab first.", true);
    return;
  }
  fillSelect(document.getElementById("import-form").elements.meet_id, state.meets, (m) => `${m.name} (${m.date})`);
  importDialog.open("Import meet results", {
    meet_id: document.getElementById("filter-meet").value || newestMeet().id,
  });
}

document.getElementById("import-results").addEventListener("click", openImportDialog);

// ---------------------------------------------------------------------------
// Time standards (read-only reference data, one organization + season at a time)
// ---------------------------------------------------------------------------

const STROKE_LABELS = { FR: "Free (FR)", BK: "Back (BK)", BR: "Breast (BR)", FL: "Fly (FL)", IM: "IM" };
const COURSE_ORDER = { SCY: 0, SCM: 1, LCM: 2 };
const GENDER_LABELS = { F: "Girls", M: "Boys" };

// Standards are big (thousands of rows) and never change while the page is open,
// so each set is fetched only when first selected, then kept.
const standardsCache = new Map(); // setKey -> rows, or a Promise while loading

const setKey = (s) => `${s.organization}|${s.season}`;
const setLabel = (s) => `${s.organization} (${s.season})`;

/** "8 & Under" < "10 & Under/9-10" < "11-12" < "15-16/17 & Over/Senior": by the first number in the name. */
function ageGroupOrder(a, b) {
  const first = (s) => Number((s.match(/\d+/) || [Infinity])[0]);
  return first(a) - first(b) || a.localeCompare(b);
}

/** Replace a select's options with `values` (plus a leading "All"), keeping the current choice if it's still offered. */
function fillFilter(select, values, labelFn) {
  const current = select.value;
  select.replaceChildren(el("option", { value: "", textContent: "All" }));
  for (const v of values) select.append(el("option", { value: String(v), textContent: labelFn(v) }));
  select.value = values.map(String).includes(current) ? current : "";
}

// Age groups ticked in the Age groups filter. Empty means all of them.
const selectedAgeGroups = new Set();

/** Rebuild the age-group checkboxes for this set, dropping any ticked group it doesn't have. */
function fillAgeGroupFilter(ageGroups) {
  for (const a of [...selectedAgeGroups]) if (!ageGroups.includes(a)) selectedAgeGroups.delete(a);
  const container = document.getElementById("standard-age-options");
  const focused = container.contains(document.activeElement) ? document.activeElement.value : null;
  container.replaceChildren(
    ...ageGroups.map((a) => {
      const box = el("input", { type: "checkbox", value: a, checked: selectedAgeGroups.has(a) });
      box.addEventListener("change", () => {
        if (box.checked) selectedAgeGroups.add(a);
        else selectedAgeGroups.delete(a);
        renderStandards();
      });
      return el("label", { class: "check" }, box, " ", a);
    })
  );
  // Ticking a box re-renders the list; keep focus on that box for keyboard users.
  if (focused !== null) [...container.querySelectorAll("input")].find((b) => b.value === focused)?.focus();
  document.getElementById("standard-age-summary").textContent = selectedAgeGroups.size
    ? ageGroups.filter((a) => selectedAgeGroups.has(a)).join(", ")
    : "All";
}

/** The age-group dropdown is a <details>, which has no `disabled`; this stands in for it. */
function setAgeGroupFilterEnabled(enabled) {
  const details = document.getElementById("standard-age");
  details.setAttribute("aria-disabled", String(!enabled));
  if (!enabled) details.open = false;
}

function renderStandards() {
  const setSelect = document.getElementById("standard-set");
  const filters = ["distance", "stroke", "course", "gender"].map((f) => document.getElementById(`standard-${f}`));
  const [distanceSelect, strokeSelect, courseSelect, genderSelect] = filters;
  const table = document.getElementById("standards-table");
  const empty = document.getElementById("standards-empty");

  // The placeholder can't be picked again once a standard is chosen: exactly one is shown at a time.
  const chosen = setSelect.value;
  setSelect.replaceChildren(
    el("option", { value: "", textContent: "Select a standard…", disabled: true }),
    ...state.standardSets.map((s) => el("option", { value: setKey(s), textContent: setLabel(s) })),
  );
  setSelect.value = state.standardSets.some((s) => setKey(s) === chosen) ? chosen : "";

  const showMessage = (text) => {
    document.getElementById("standards-head").replaceChildren();
    document.getElementById("standards-body").replaceChildren();
    table.hidden = true;
    empty.hidden = false;
    empty.textContent = text;
  };

  const rows = standardsCache.get(setSelect.value);
  if (!setSelect.value || !Array.isArray(rows)) {
    filters.forEach((s) => (s.disabled = true));
    setAgeGroupFilterEnabled(false);
    if (!state.standardSets.length) {
      showMessage("No time standards loaded yet. Import them with import_time_standards.py.");
    } else if (!setSelect.value) {
      showMessage("Select a standard to see its times.");
    } else {
      showMessage("Loading…");
      loadStandardSet(setSelect.value);
    }
    return;
  }

  // Filter choices come from the events this set actually covers.
  const events = byId(state.events);
  const setEvents = [...new Set(rows.map((r) => r.event_id))].map((id) => events.get(id)).filter(Boolean);
  const unique = (values) => [...new Set(values)];
  fillFilter(distanceSelect, unique(setEvents.map((e) => e.distance)).sort((a, b) => a - b), (d) => String(d));
  fillFilter(strokeSelect, unique(setEvents.map((e) => e.stroke)).sort((a, b) => STROKE_ORDER[a] - STROKE_ORDER[b]),
    (s) => STROKE_LABELS[s] || s);
  fillFilter(courseSelect, unique(setEvents.map((e) => e.course)).sort((a, b) => COURSE_ORDER[a] - COURSE_ORDER[b]),
    (c) => c);
  fillFilter(genderSelect, unique(rows.map((r) => r.gender)).sort(), (g) => GENDER_LABELS[g] || g);
  // Age groups differ by organization (MN has "8 & Under", USA doesn't), so offer only this set's.
  fillAgeGroupFilter(unique(rows.map((r) => r.age_group)).sort(ageGroupOrder));
  filters.forEach((s) => (s.disabled = false));
  setAgeGroupFilterEnabled(true);

  const distance = Number(distanceSelect.value) || null;
  const stroke = strokeSelect.value || null;
  const course = courseSelect.value || null;
  const gender = genderSelect.value || null;

  // Tiers become columns, in the organization's own order (e.g. B, BB, A ... or BRNZ, SLVR, GOLD ...).
  const tiers = unique(
    [...rows].sort((a, b) => a.standard_rank - b.standard_rank).map((r) => r.standard_name),
  );

  // One table row per event + age group + gender, holding a time for each tier.
  const lines = new Map();
  for (const r of rows) {
    const event = events.get(r.event_id);
    if (!event) continue;
    if ((distance && event.distance !== distance) || (stroke && event.stroke !== stroke) ||
        (course && event.course !== course) || (gender && r.gender !== gender) ||
        (selectedAgeGroups.size && !selectedAgeGroups.has(r.age_group))) continue;
    const key = `${r.age_group}|${event.id}|${r.gender}`;
    if (!lines.has(key)) lines.set(key, { ageGroup: r.age_group, event, gender: r.gender, times: {} });
    lines.get(key).times[r.standard_name] = r.time_seconds;
  }
  const sorted = [...lines.values()].sort((a, b) =>
    ageGroupOrder(a.ageGroup, b.ageGroup) ||
    STROKE_ORDER[a.event.stroke] - STROKE_ORDER[b.event.stroke] ||
    a.event.distance - b.event.distance ||
    COURSE_ORDER[a.event.course] - COURSE_ORDER[b.event.course] ||
    a.gender.localeCompare(b.gender)
  );

  if (!sorted.length) {
    showMessage("No standards match these filters.");
    return;
  }

  document.getElementById("standards-head").replaceChildren(
    el("tr", {},
      el("th", { textContent: "Event" }),
      el("th", { textContent: "Gender" }),
      ...tiers.map((t) => el("th", { textContent: t })))
  );

  const groups = [];
  for (const line of sorted) {
    if (!groups.length || groups[groups.length - 1].ageGroup !== line.ageGroup) {
      groups.push({ ageGroup: line.ageGroup, lines: [] });
    }
    groups[groups.length - 1].lines.push(line);
  }

  // Age groups can be collapsed only when more than one is on screen; a lone group always shows its rows.
  const collapsible = groups.length > 1;
  const body = [];
  for (const { ageGroup, lines: groupLines } of groups) {
    const key = `${setSelect.value}|${ageGroup}`;
    const collapsed = collapsible && collapsedAgeGroups.has(key);
    body.push(el("tr", { class: collapsed ? "group-heading age-heading collapsed" : "group-heading age-heading" },
      el("th", { colSpan: 2 + tiers.length, scope: "colgroup" },
        collapsible
          ? groupToggle({
            label: ageGroup, labelClass: "age-name", key,
            collapsedSet: collapsedAgeGroups, rerender: renderStandards, what: "standards",
          })
          : el("span", { class: "age-name", textContent: ageGroup }),
        ...hiddenCount(collapsed, groupLines.length, "standard", "standards"))));
    if (collapsed) continue;
    for (const line of groupLines) {
      body.push(el("tr", { class: "standard" },
        el("td", { class: "c-event", textContent: line.event.name }),
        el("td", { class: "c-gender", textContent: GENDER_LABELS[line.gender] || line.gender }),
        ...tiers.map((t) => line.times[t] === undefined
          ? el("td", { class: "c-standard pending", textContent: "—" })
          : el("td", { class: "c-standard", textContent: formatTime(line.times[t]) }))));
    }
  }
  document.getElementById("standards-body").replaceChildren(...body);
  table.hidden = false;
  empty.hidden = true;
}

async function loadStandardSet(key) {
  if (standardsCache.has(key)) return; // already loaded, or loading
  const set = state.standardSets.find((s) => setKey(s) === key);
  const params = new URLSearchParams({ organization: set.organization, season: set.season });
  const loading = api("GET", `/time_standards/?${params}`);
  standardsCache.set(key, loading);
  try {
    standardsCache.set(key, await loading);
  } catch (err) {
    standardsCache.delete(key);
    // Back to "Select a standard…"; choosing it again retries.
    document.getElementById("standard-set").value = "";
    toast(`Couldn't load ${setLabel(set)}: ${err.message}`, true);
  }
  renderStandards();
}

for (const id of ["standard-set", "standard-distance", "standard-stroke", "standard-course", "standard-gender"]) {
  document.getElementById(id).addEventListener("change", renderStandards);
}

// Age groups dropdown: can't open while disabled; closes on "Show all", Escape, or a click outside it.
const ageDetails = document.getElementById("standard-age");
ageDetails.querySelector("summary").addEventListener("click", (ev) => {
  if (ageDetails.getAttribute("aria-disabled") === "true") ev.preventDefault();
});
document.getElementById("standard-age-all").addEventListener("click", () => {
  selectedAgeGroups.clear();
  ageDetails.open = false;
  renderStandards();
});
document.addEventListener("click", (ev) => {
  if (ageDetails.open && !ageDetails.contains(ev.target)) ageDetails.open = false;
});
ageDetails.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && ageDetails.open) {
    ageDetails.open = false;
    ageDetails.querySelector("summary").focus();
  }
});

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
