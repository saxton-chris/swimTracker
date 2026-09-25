// JSON API calls. Every failure becomes an Error whose message is ready to show the user.

export async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(data, res));
  return data;
}

/** POST a file as the raw request body (e.g. a results PDF) and return the JSON reply. */
export async function upload(path, file) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/pdf" }, body: file });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(data, res));
  return data;
}

export function errorMessage(data, res) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors
    return detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  return `${res.status} ${res.statusText}`;
}
