export const VIEWS = ["entries", "swimmers", "meets", "standards"];

const tabs = () => [...document.querySelectorAll(".tab")];

/** Show one tab's section (unknown names fall back to Entries) and record it in the URL hash. */
export function showView(name) {
  if (!VIEWS.includes(name)) name = "entries";
  for (const v of VIEWS) document.getElementById(`view-${v}`).hidden = v !== name;
  for (const tab of tabs()) {
    const selected = tab.dataset.view === name;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1; // only the selected tab is in the Tab order; arrows move between them
  }
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
}

/** ARIA tabs: click to select; Left/Right (wrapping), Home and End move to and select another tab. */
export function initTabs() {
  for (const tab of tabs()) {
    tab.addEventListener("click", () => showView(tab.dataset.view));
    tab.addEventListener("keydown", (ev) => {
      const all = tabs();
      const i = all.indexOf(tab);
      const next = {
        ArrowRight: all[(i + 1) % all.length],
        ArrowLeft: all[(i - 1 + all.length) % all.length],
        Home: all[0],
        End: all[all.length - 1],
      }[ev.key];
      if (!next) return;
      ev.preventDefault();
      showView(next.dataset.view);
      next.focus();
    });
  }
}
