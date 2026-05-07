// Client wrapper over /api/saves.
//
// Same-origin fetches send the Clerk session cookie automatically.
// Each function returns either the parsed payload or null on
// non-2xx, with the HTTP status surfaced via `error` on failure
// (used by the toast in app.jsx to distinguish "not signed in",
// "save cap reached", "everything broke").

async function parseJsonOrNull(res) {
  try { return await res.json(); } catch { return null; }
}

export async function fetchSaves() {
  const res = await fetch("/api/saves", {
    method: "GET",
    credentials: "same-origin",
  });
  if (!res.ok) {
    const detail = await parseJsonOrNull(res);
    return { ok: false, status: res.status, error: detail && detail.error };
  }
  const json = await res.json();
  return { ok: true, saves: json.saves || [], cap: json.cap, plan: json.plan };
}

export async function postSaveAction(listingId, action) {
  const res = await fetch("/api/saves", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ listing_id: listingId, action }),
  });
  if (!res.ok) {
    const detail = await parseJsonOrNull(res);
    return {
      ok: false,
      status: res.status,
      error: detail && detail.error,
      cap: detail && detail.cap,
    };
  }
  const json = await res.json();
  return { ok: true, saves: json.saves || [], cap: json.cap, plan: json.plan };
}
