// Personal records: each swimmer's fastest official time in each individual event.

import { byId, state } from "./store.js";

/**
 * Map of "swimmerId|eventId" -> {entry, time, meet, event}: the swimmer's fastest timed, non-DQ swim
 * in that event (events are per course, so 50 FR SCY and 50 FR LCM each have their own PR).
 * Relays are left out, since a team time isn't a personal record. A tie goes to the earlier meet,
 * where the time was first swum.
 */
export function personalRecords() {
  const meets = byId(state.meets);
  const events = byId(state.events);
  const timeByEntry = new Map(state.times.map((t) => [t.meet_entry_id, t]));
  const prs = new Map();
  for (const entry of state.entries) {
    const time = timeByEntry.get(entry.id);
    const event = events.get(entry.event_id);
    if (!time || time.dq || time.time_seconds == null || !event || event.relay) continue;
    const meet = meets.get(entry.meet_id);
    const key = `${entry.swimmer_id}|${entry.event_id}`;
    const best = prs.get(key);
    if (
      !best ||
      time.time_seconds < best.time.time_seconds ||
      (time.time_seconds === best.time.time_seconds &&
        (meet.date.localeCompare(best.meet.date) || meet.name.localeCompare(best.meet.name)) < 0)
    ) {
      prs.set(key, { entry, time, meet, event });
    }
  }
  return prs;
}

/** Ids of the meet entries that hold a PR (for the badge on the Entries tab). */
export const prEntryIds = (prs = personalRecords()) => new Set([...prs.values()].map((pr) => pr.entry.id));
