// Time Standards tab: read-only reference data, one organization + season at a time.

import { api } from "../api.js";
import { groupToggle, hiddenCount, storedSet } from "../collapse.js";
import { el } from "../dom.js";
import { formatTime } from "../format.js";
import { COURSE_ORDER, STROKE_ORDER, byId, state } from "../store.js";
import { toast } from "../toast.js";

const STROKE_LABELS = { FR: "Free (FR)", BK: "Back (BK)", BR: "Breast (BR)", FL: "Fly (FL)", IM: "IM" };
const GENDER_LABELS = { F: "Girls", M: "Boys" };

// Standards are big (thousands of rows) and never change while the page is open,
// so each set is fetched only when first selected, then kept.
const standardsCache = new Map(); // setKey -> rows, or a Promise while loading

const collapsedAgeGroups = storedSet("swimTracker.collapsedAgeGroups"); // "org|season|age group"

// Age groups ticked in the Age groups filter. Empty means all of them.
const selectedAgeGroups = new Set();

const setKey = (s) => `${s.organization}|${s.season}`;
const setLabel = (s) => `${s.organization} (${s.season})`;
const unique = (values) => [...new Set(values)];

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

export function renderStandards() {
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
