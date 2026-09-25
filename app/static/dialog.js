import { refresh } from "./store.js";

/**
 * Wires a <dialog> form: cancel closes it, submit runs `onSave(formData)`.
 * If onSave throws, the error is shown inside the dialog and it stays open.
 */
export function setupDialog(dialogId, onSave) {
  const dialog = document.getElementById(dialogId);
  const form = dialog.querySelector("form");
  const error = form.querySelector(".form-error");
  const submit = form.querySelector('button[type="submit"]');

  form.querySelector(".cancel").addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    error.hidden = true;
    submit.disabled = true;
    try {
      await onSave(Object.fromEntries(new FormData(form)));
      dialog.close();
      await refresh();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });

  return {
    open(title, values) {
      form.reset();
      error.hidden = true;
      form.querySelector("h2").textContent = title;
      for (const [name, value] of Object.entries(values)) {
        const field = form.elements[name];
        if (!field) continue;
        if (field.type === "checkbox") field.checked = Boolean(value);
        else field.value = value ?? "";
      }
      form.dispatchEvent(new Event("change")); // let the form sync any fields that depend on these values
      dialog.showModal();
    },
  };
}
