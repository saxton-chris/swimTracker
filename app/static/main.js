// Entry point: wires the tabs together and loads the data.
//
// Module layout:
//   api.js, format.js, dom.js, toast.js   helpers with no app state
//   store.js     the loaded data, refresh() and mutate()
//   dialog.js    <dialog> form plumbing
//   collapse.js  collapsible group headings (meets, age groups)
//   tabs.js      which tab is showing
//   views/*.js   one module per tab (plus the import dialog), each exporting its render function

import { onRefresh, refresh } from "./store.js";
import { showView } from "./tabs.js";
import { renderEntries } from "./views/entries.js";
import "./views/import.js";
import { renderMeets } from "./views/meets.js";
import { renderStandards } from "./views/standards.js";
import { renderSwimmers } from "./views/swimmers.js";

// Drawn in this order after every refresh.
onRefresh(renderSwimmers);
onRefresh(renderMeets);
onRefresh(renderEntries);
onRefresh(renderStandards);

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => showView(tab.dataset.view))
);

showView(location.hash.slice(1));
refresh();
