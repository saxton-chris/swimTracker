// Time standards shared by the Time Standards tab and the Entries tab: fetching and caching a
// set (one organization + season), and working out which standard a swim reached.

import { api } from "./api.js";

export const setKey = (s) => `${s.organization}|${s.season}`;
export const setLabel = (s) => `${s.organization} (${s.season})`;

// Standards are big (thousands of rows) and never change while the page is open,
// so each set is fetched once, the first time either tab needs it.
const cache = new Map(); // setKey -> rows, or a Promise while loading
const indexes = new Map(); // setKey -> lookup built by indexSet()

/** The set's rows if they're loaded, else null. */
export function loadedSet(key) {
  const rows = cache.get(key);
  return Array.isArray(rows) ? rows : null;
}

/** Fetch a set (once). Resolves to its rows; on failure the set is forgotten so a later call retries. */
export async function loadSet(set) {
  const key = setKey(set);
  if (!cache.has(key)) {
    const params = new URLSearchParams({ organization: set.organization, season: set.season });
    cache.set(key, api("GET", `/time_standards/?${params}`));
  }
  try {
    const rows = await cache.get(key);
    cache.set(key, rows);
    return rows;
  } catch (err) {
    cache.delete(key);
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Age groups
// ---------------------------------------------------------------------------

/**
 * The ages an age-group label covers, as [min, max]:
 * "11-12" -> [11, 12], "10 & under" -> [0, 10], "10 & Under/9-10" -> [0, 10],
 * "15-16/17 & Over/Senior" -> [15, 99]. Null if the label has no ages in it.
 */
export function ageRange(label) {
  let min = Infinity;
  let max = -Infinity;
  for (const part of label.split("/")) {
    let m;
    if ((m = part.match(/(\d+)\s*-\s*(\d+)/))) {
      min = Math.min(min, Number(m[1]));
      max = Math.max(max, Number(m[2]));
    } else if ((m = part.match(/(\d+)\s*&\s*under/i))) {
      min = 0;
      max = Math.max(max, Number(m[1]));
    } else if ((m = part.match(/(\d+)\s*&\s*over/i))) {
      min = Math.min(min, Number(m[1]));
      max = 99;
    }
  }
  return min <= max ? [min, max] : null;
}

/** The age group for `age`: the narrowest one covering it (so an 8-year-old in MN is "8 & Under",
 * not "10 & Under/9-10"). Null if none does. */
export function ageGroupFor(ageGroups, age) {
  let best = null;
  let bestSpan = Infinity;
  for (const group of ageGroups) {
    const range = ageRange(group);
    if (range && range[0] <= age && age <= range[1] && range[1] - range[0] < bestSpan) {
      best = group;
      bestSpan = range[1] - range[0];
    }
  }
  return best;
}

// ---------------------------------------------------------------------------
// Which standard a time reached
// ---------------------------------------------------------------------------

/**
 * A lookup for one set: its age groups, and for each event + gender + age group the tiers
 * slowest first, e.g. [{name: "B", rank: 1, seconds: 35.19}, {name: "BB", ...}, ...].
 */
export function indexSet(key) {
  const rows = loadedSet(key);
  if (!rows) return null;
  if (!indexes.has(key)) {
    const tiers = new Map();
    for (const r of rows) {
      const k = `${r.event_id}|${r.gender}|${r.age_group}`;
      if (!tiers.has(k)) tiers.set(k, []);
      tiers.get(k).push({ name: r.standard_name, rank: r.standard_rank, seconds: r.time_seconds });
    }
    for (const list of tiers.values()) list.sort((a, b) => a.rank - b.rank);
    indexes.set(key, { ageGroups: [...new Set(rows.map((r) => r.age_group))], tiers });
  }
  return indexes.get(key);
}

/**
 * Where `seconds` stands against `tiers` (slowest first). A standard is reached when the time is
 * at or under its cut. Returns {achieved, next, toNext}: the best tier reached (or null), the
 * next tier up (or null at the top), and how many seconds faster the next one needs.
 */
export function standingFor(seconds, tiers) {
  let achieved = null;
  let next = null;
  for (const tier of tiers) {
    if (seconds <= tier.seconds + 1e-9) {
      achieved = tier;
    } else {
      next = tier;
      break;
    }
  }
  const toNext = next ? Math.round((seconds - next.seconds) * 100) / 100 : null;
  return { achieved, next, toNext };
}
