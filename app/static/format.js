// Pure formatting and parsing helpers (no DOM, no state).

/** 62.45 -> "1:02.45", 32.4 -> "32.40" */
export function formatTime(seconds) {
  const hundredths = Math.round(seconds * 100);
  const mins = Math.floor(hundredths / 6000);
  const rest = ((hundredths % 6000) / 100).toFixed(2);
  return mins ? `${mins}:${rest.padStart(5, "0")}` : rest;
}

/** "1:02.45" or "62.45" -> 62.45. Returns null for blank, throws on garbage. */
export function parseTime(text) {
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
export function formatDate(iso) {
  return DATE_FORMAT.format(localDate(iso));
}

/** A meet's dates: "Jan 10, 2026" for one day, "Jan 9 – 11, 2026" for a multi-day meet. */
export function formatMeetDates(meet) {
  if (!meet.end_date || meet.end_date === meet.date) return formatDate(meet.date);
  return DATE_FORMAT.formatRange(localDate(meet.date), localDate(meet.end_date));
}

export function ageOn(birthIso, onDate = new Date()) {
  const [y, m, d] = birthIso.split("-").map(Number);
  let age = onDate.getFullYear() - y;
  if (onDate.getMonth() + 1 < m || (onDate.getMonth() + 1 === m && onDate.getDate() < d)) age--;
  return age;
}

/** plural(1, "entry", "entries") -> "1 entry"; plural(3, ...) -> "3 entries" */
export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** Trimmed text, or null when the field was left blank (for optional form fields). */
export const blankToNull = (s) => (s && s.trim() ? s.trim() : null);
