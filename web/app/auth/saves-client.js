// Client wrapper over /api/saves.
//
// Same-origin fetches send the Clerk session cookie automatically.
// Each function returns either the parsed payload or null on
// non-2xx, with the HTTP status surfaced via `error` on failure
// (used by the toast in app.jsx to distinguish "not signed in",
// "save cap reached", "everything broke").
//
// Non-2xx responses also fire `api.error` to PostHog so we can
// triage rate / class of failures from the dashboard without
// having to ask Sebastian to dig through Vercel runtime logs.

import { track } from "../telemetry/hook";

async function parseJsonOrNull(res) {
  try { return await res.json(); } catch { return null; }
}

function reportApiError(endpoint, status, detail) {
  try {
    track("api.error", {
      endpoint,
      status,
      reason: detail && detail.error,
      detail: detail && detail.detail,
    });
  } catch {
    // Telemetry must never break the API call's own error handling.
  }
}

export async function fetchSaves() {
  const res = await fetch("/api/saves", {
    method: "GET",
    credentials: "same-origin",
  });
  if (!res.ok) {
    const detail = await parseJsonOrNull(res);
    reportApiError("/api/saves[GET]", res.status, detail);
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
    reportApiError("/api/saves[POST]", res.status, detail);
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
