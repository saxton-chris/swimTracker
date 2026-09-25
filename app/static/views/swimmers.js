// Swimmers tab.

import { api } from "../api.js";
import { setupDialog } from "../dialog.js";
import { actionButton, el, nameButton } from "../dom.js";
import { ageOn, blankToNull, formatDate } from "../format.js";
import { cascadeWarning, mutate, state } from "../store.js";
import { toast } from "../toast.js";
import { filterEntries } from "./entries.js";

export function renderSwimmers() {
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
