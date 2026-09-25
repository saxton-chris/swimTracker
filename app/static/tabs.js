export const VIEWS = ["entries", "swimmers", "meets", "standards"];

/** Show one tab's section (unknown names fall back to Entries) and record it in the URL hash. */
export function showView(name) {
  if (!VIEWS.includes(name)) name = "entries";
  for (const v of VIEWS) document.getElementById(`view-${v}`).hidden = v !== name;
  for (const tab of document.querySelectorAll(".tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === name));
  }
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
}
