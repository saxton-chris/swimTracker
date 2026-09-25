// Progress chart: one swimmer's results in one event across meets, drawn with Plotly.js.
// Plotly (vendor/, ~1 MB) is only loaded the first time a chart is opened.

import { formatDate, formatTime, plural } from "./format.js";
import { byId, state } from "./store.js";

const PLOTLY_SRC = "/static/vendor/plotly-basic-4.1.1.min.js";
let plotlyLoading = null;

/** Load Plotly once (a classic script that sets window.Plotly); resolves to it. */
export function loadPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  plotlyLoading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PLOTLY_SRC;
    script.onload = () => resolve(window.Plotly);
    script.onerror = () => {
      plotlyLoading = null; // let a later click retry
      reject(new Error("Couldn't load the charting library."));
    };
    document.head.append(script);
  });
  return plotlyLoading;
}

/**
 * The points to chart: this swimmer's timed results in this event, oldest meet first.
 * DQs and entries without a time are left out. Also returns how many DQs were skipped.
 */
export function progressPoints(swimmerId, eventId) {
  const meets = byId(state.meets);
  const timeByEntry = new Map(state.times.map((t) => [t.meet_entry_id, t]));
  const points = [];
  let dqs = 0;
  for (const entry of state.entries) {
    if (entry.swimmer_id !== swimmerId || entry.event_id !== eventId) continue;
    const time = timeByEntry.get(entry.id);
    if (!time) continue;
    if (time.dq) {
      dqs++;
      continue;
    }
    const meet = meets.get(entry.meet_id);
    points.push({ date: meet.date, meet: meet.name, seconds: time.time_seconds, leg: time.relay_leg, split: time.split_seconds });
  }
  points.sort((a, b) => a.date.localeCompare(b.date) || a.meet.localeCompare(b.meet));
  return { points, dqs };
}

/**
 * Y-axis scale for times between `min` and `max` seconds: at most ~5 ticks on a "nice" step,
 * labeled like the rest of the app ("58.00", "1:02.00"), and the axis range to draw
 * (the data plus half a step either side; at least 1 second tall, so one result isn't a zoomed-in sliver).
 */
export function timeTicks(min, max) {
  if (max - min < 1) {
    const grow = (1 - (max - min)) / 2;
    min -= grow;
    max += grow;
  }
  const span = max - min;
  const steps = [0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const step = steps.find((s) => span / s <= 5) ?? 600;
  const first = Math.floor(min / step) * step;
  const values = [];
  for (let v = first; v <= max + step / 2; v += step) values.push(Math.round(v * 100) / 100);
  return { values, labels: values.map(formatTime), step, range: [min - step / 2, max + step / 2] };
}

/** Plotly renders hover text as (restricted) HTML, so user text goes in escaped. */
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

/** Draw the chart into `container` (or show `emptyEl` when there's nothing to plot). Returns the points. */
export async function drawProgressChart(container, emptyEl, swimmerId, event) {
  const { points, dqs } = progressPoints(swimmerId, event.id);
  emptyEl.hidden = points.length > 0;
  container.hidden = points.length === 0;
  const Plotly = await loadPlotly();
  if (!points.length) {
    Plotly.purge(container);
    return { points, dqs };
  }

  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();
  const seconds = points.map((p) => p.seconds);
  const ticks = timeTicks(Math.min(...seconds), Math.max(...seconds));

  const trace = {
    type: "scatter",
    mode: points.length > 1 ? "lines+markers" : "markers",
    x: points.map((p) => p.date),
    y: seconds,
    customdata: points.map((p) => [
      escapeHtml(p.meet),
      formatDate(p.date),
      formatTime(p.seconds),
      event.relay && p.leg != null
        ? `<br>Leg ${p.leg}${p.split != null ? ` · split ${formatTime(p.split)}` : ""}`
        : "",
    ]),
    hovertemplate: "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>Time: %{customdata[2]}%{customdata[3]}<extra></extra>",
    line: { color: color("--orange"), width: 2.5 },
    marker: { size: 10, color: color("--orange"), line: { color: color("--surface"), width: 2 } },
  };
  const layout = {
    margin: { l: 70, r: 20, t: 10, b: 50 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Barlow, system-ui, sans-serif", color: color("--text"), size: 13 },
    showlegend: false,
    hovermode: "closest",
    hoverlabel: { bgcolor: "#000", bordercolor: color("--orange"), font: { color: "#fff", size: 14 }, align: "left" },
    xaxis: { type: "date", gridcolor: color("--border"), linecolor: color("--border"), zeroline: false },
    yaxis: {
      // Faster (smaller) times at the top, so improvement reads as going up.
      range: [ticks.range[1], ticks.range[0]],
      tickmode: "array",
      tickvals: ticks.values,
      ticktext: ticks.labels,
      gridcolor: color("--border"),
      zeroline: false,
      title: { text: "Time (faster ↑)", font: { color: color("--muted") } },
    },
  };
  await Plotly.react(container, [trace], layout, { displayModeBar: false, responsive: true });
  return { points, dqs };
}

/** "5 swims · best 32.45 at Winter Invite (Jan 10, 2026) · 2 DQs not shown" */
export function progressSummary(points, dqs) {
  const parts = [];
  if (points.length) {
    const best = points.reduce((a, b) => (b.seconds < a.seconds ? b : a));
    parts.push(plural(points.length, "swim", "swims"));
    parts.push(`best ${formatTime(best.seconds)} at ${best.meet} (${formatDate(best.date)})`);
  }
  if (dqs) parts.push(`${plural(dqs, "DQ", "DQs")} not shown`);
  return parts.join(" · ");
}
