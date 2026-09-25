// "Import results" on the Entries tab: upload a Hy-Tek results PDF for a meet.

import { upload } from "../api.js";
import { setupDialog } from "../dialog.js";
import { fillSelect } from "../dom.js";
import { plural } from "../format.js";
import { newestMeet, state } from "../store.js";
import { toast } from "../toast.js";

/** One-line summary of a POST /meets/{id}/import-results reply. */
export function importSummary(r) {
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
