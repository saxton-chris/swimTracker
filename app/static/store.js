// App data. The whole dataset is small, so every list is loaded up front and
// reloaded after each change instead of patching local copies.

import { api } from "./api.js";
import { toast } from "./toast.js";

export const state = {
  swimmers: [],
  meets: [],
  events: [],
  entries: [],
  times: [],
  standardSets: [], // [{organization, season}] that have standards loaded
};

export const byId = (list) => new Map(list.map((x) => [x.id, x]));
export const STROKE_ORDER = { FR: 0, BK: 1, BR: 2, FL: 3, IM: 4 };
export const COURSE_ORDER = { SCY: 0, SCM: 1, LCM: 2 };

export async function loadAll() {
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

/** Default meet for a new entry or import: the most recent one (meets are listed oldest first). */
export const newestMeet = () => state.meets[state.meets.length - 1];

/** "\n\nThis will also delete 3 meet entries and 2 results." for the confirm prompt. */
export function cascadeWarning(entries) {
  if (!entries.length) return "";
  const ids = new Set(entries.map((e) => e.id));
  const results = state.times.filter((t) => ids.has(t.meet_entry_id)).length;
  const entryText = entries.length === 1 ? "1 meet entry" : `${entries.length} meet entries`;
  const resultText = results === 1 ? "1 result" : `${results} results`;
  return `\n\nThis will also delete ${entryText}` + (results ? ` and ${resultText}.` : ".");
}

// Each tab registers how to draw itself; refresh() reloads the data and redraws them all.
// (Registering, rather than importing the views here, keeps this module free of import cycles.)
const renderers = [];

export function onRefresh(render) {
  renderers.push(render);
}

export async function refresh() {
  try {
    await loadAll();
    for (const render of renderers) render();
  } catch (err) {
    toast(`Couldn't load data: ${err.message}`, true);
  }
}

/** Run a change, report it, then reload everything. */
export async function mutate(fn, successMessage) {
  try {
    await fn();
    toast(successMessage);
  } catch (err) {
    toast(err.message, true);
  }
  await refresh();
}
