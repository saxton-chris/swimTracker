// PRs tab: one swimmer's personal record in every individual event they've swum, grouped by course.

import { el } from "../dom.js";
import { formatMeetDates, formatTime } from "../format.js";
import { personalRecords } from "../prs.js";
import { COURSE_ORDER, STROKE_ORDER, state } from "../store.js";
import { openProgressChart } from "./entries.js";

const PR_COLUMNS = 3;
const COURSE_NAMES = { SCY: "Short course yards", SCM: "Short course meters", LCM: "Long course meters" };

/** The swimmer dropdown: a "Select a swimmer…" placeholder until one is picked (not remembered across loads). */
function fillSwimmerSelect() {
  const select = document.getElementById("pr-swimmer");
  const current = select.value;
  select.replaceChildren(
    el("option", { value: "", textContent: "Select a swimmer…", disabled: true }),
    ...state.swimmers.map((s) => el("option", { value: String(s.id), textContent: s.name })),
  );
  // Falls back to the placeholder if the chosen swimmer was deleted.
  select.value = state.swimmers.some((s) => String(s.id) === current) ? current : "";
  return state.swimmers.find((s) => String(s.id) === select.value) ?? null;
}

export function renderPrs() {
  const swimmer = fillSwimmerSelect();
  const table = document.getElementById("prs-table");
  const empty = document.getElementById("prs-empty");

  const prs = swimmer
    ? [...personalRecords().values()]
      .filter((pr) => pr.entry.swimmer_id === swimmer.id)
      .sort((a, b) =>
        COURSE_ORDER[a.event.course] - COURSE_ORDER[b.event.course] ||
        STROKE_ORDER[a.event.stroke] - STROKE_ORDER[b.event.stroke] ||
        a.event.distance - b.event.distance)
    : [];

  const rows = [];
  let course = null;
  for (const pr of prs) {
    if (pr.event.course !== course) {
      course = pr.event.course;
      rows.push(el("tr", { class: "group-heading course-heading" },
        el("th", { colSpan: PR_COLUMNS, scope: "colgroup", textContent: COURSE_NAMES[course] ?? course })));
    }
    rows.push(prRow(swimmer, pr));
  }
  document.getElementById("prs-body").replaceChildren(...rows);

  table.hidden = prs.length === 0;
  empty.hidden = prs.length > 0;
  if (!state.swimmers.length) empty.textContent = "No swimmers yet. Add a swimmer on the Swimmers tab.";
  else if (!swimmer) empty.textContent = "Select a swimmer to see their personal records.";
  else empty.textContent = `No timed individual swims for ${swimmer.name} yet.`;
}

function prRow(swimmer, { event, time, meet }) {
  return el("tr", { class: "pr" },
    el("td", { class: "c-event" },
      el("button", {
        type: "button",
        class: "link event-link",
        textContent: event.name,
        title: `${swimmer.name}'s ${event.name} over time`,
        onclick: () => openProgressChart(swimmer, event),
      })),
    el("td", { class: "c-time" }, el("span", { class: "clock", textContent: formatTime(time.time_seconds) })),
    el("td", { class: "c-meet" },
      el("span", { class: "pr-meet", textContent: meet.name }),
      el("span", { class: "pr-date", textContent: formatMeetDates(meet) })),
  );
}

document.getElementById("pr-swimmer").addEventListener("change", renderPrs);
