// Meets tab.

import { api } from "../api.js";
import { setupDialog } from "../dialog.js";
import { actionButton, el, nameButton } from "../dom.js";
import { blankToNull, formatMeetDates } from "../format.js";
import { cascadeWarning, mutate, state } from "../store.js";
import { toast } from "../toast.js";
import { filterEntries } from "./entries.js";

export function renderMeets() {
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
