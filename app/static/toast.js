// The one status message at the bottom of the page.

let toastTimer;

export function toast(message, isError = false, ms = isError ? 6000 : 2500) {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.className = isError ? "toast error" : "toast";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}
