// Collapsible groups (meets on Entries, age groups on Time Standards).

import { el } from "./dom.js";
import { plural } from "./format.js";

/**
 * A Set of collapsed group keys, kept in this browser only (a display
 * preference, not data). Storage is optional: without it nothing is remembered.
 */
export function storedSet(storageKey) {
  let set;
  try {
    set = new Set(JSON.parse(localStorage.getItem(storageKey)) || []);
  } catch {
    set = new Set();
  }
  set.toggle = (key) => {
    if (set.has(key)) set.delete(key);
    else set.add(key);
    try {
      localStorage.setItem(storageKey, JSON.stringify([...set]));
    } catch {
      // storage unavailable: the choice still applies until the page reloads
    }
  };
  return set;
}

/**
 * The disclosure button at the start of a group heading row. Clicking it flips
 * `key` in `collapsedSet` and calls `rerender`, then puts focus back on the new
 * button (re-rendering replaces it) so keyboard users don't lose their place.
 */
export function groupToggle({ label, labelClass, key, collapsedSet, rerender, what }) {
  const collapsed = collapsedSet.has(key);
  const toggle = el("button", {
    type: "button",
    class: "group-toggle",
    title: collapsed ? `Show ${what}` : `Hide ${what}`,
    onclick: () => {
      collapsedSet.toggle(key);
      rerender();
      document.querySelector(`.group-toggle[data-group="${CSS.escape(String(key))}"]`)?.focus();
    },
  }, el("span", { class: labelClass, textContent: label }));
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.dataset.group = String(key);
  return toggle;
}

/** " 4 entries hidden" for a collapsed heading, or nothing. */
export const hiddenCount = (collapsed, n, one, many) =>
  collapsed ? [" ", el("span", { class: "group-count", textContent: `${plural(n, one, many)} hidden` })] : [];
