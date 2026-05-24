// Client-side helper for the admin bearer-token gate.
//
// The /admin surface is open at the SPA route, but every action (every
// /api/admin/* call) requires `Authorization: Bearer <token>` where the
// token matches `PULPO_ADMIN_DEBUG_TOKEN` server-side. Sebas types the
// token once on /admin; we stash it in localStorage and thread it on
// every admin fetch.
//
// Why localStorage and not a cookie:
//   - No DB-stored session, no Clerk role; the token IS the credential.
//   - localStorage is per-origin, persists across reloads, and is
//     trivially clearable from DevTools when Sebas hands off devices.
//   - Cookies would need a separate /api/admin/login endpoint to set
//     them HTTPOnly — extra surface for marginal benefit at our scale.

const STORAGE_KEY = "pulpo_admin_token";

export function getAdminToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    const trimmed = (token || "").trim();
    if (trimmed) {
      window.localStorage.setItem(STORAGE_KEY, trimmed);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    /* localStorage disabled (private mode + Safari) — fall through */
  }
}

export function clearAdminToken(): void {
  setAdminToken("");
}

export function hasAdminToken(): boolean {
  return getAdminToken().length > 0;
}

// fetch() wrapper that auto-attaches the admin Bearer header. Use this
// for every /api/admin/* call. On a 401 it clears the stored token so
// the AdminShell's gate re-renders, prompting Sebas to enter the
// correct one.
export async function adminFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const token = getAdminToken();
  const headers = new Headers(init.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(input, { ...init, headers });
  if (res.status === 401) {
    clearAdminToken();
    // Soft-signal to AdminShell — it re-checks token presence on this event.
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("pulpo:admin-token-invalid"));
    }
  }
  return res;
}
