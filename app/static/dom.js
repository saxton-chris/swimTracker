// DOM helpers. Text always goes in through textContent, so user data is never parsed as HTML.

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node[k] = v;
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

export const actionButton = (label, onClick, danger = false) =>
  el("button", { type: "button", class: danger ? "link danger" : "link", textContent: label, onclick: onClick });

/** A swimmer/meet name that filters the Entries tab when clicked. */
export const nameButton = (label, onClick) =>
  el("button", { type: "button", class: "link name", textContent: label, onclick: onClick });

export function fillSelect(select, items, labelFn, { blank } = {}) {
  const current = select.value;
  select.replaceChildren();
  if (blank !== undefined) select.append(el("option", { value: "", textContent: blank }));
  for (const item of items) select.append(el("option", { value: String(item.id), textContent: labelFn(item) }));
  if ([...select.options].some((o) => o.value === current)) select.value = current;
}
