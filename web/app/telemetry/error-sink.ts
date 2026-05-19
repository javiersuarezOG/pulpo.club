// Server-side error sink. Audit P0-7: PostHog is the only client-side
// error pipeline today, so when PostHog is blocked (uBlock, Brave
// shields, EU-declined-consent, SDK load failure) we lose every
// client error. CLAUDE.md notes two /preview crashes have already
// shipped. The next one needs to land somewhere we can see it.
//
// This module is the dumb backup: POST to /api/client-error which
// writes a single grep-friendly line to Vercel runtime logs. The
// telemetry/client.ts captureException() path stays — both fire,
// neither blocks the other, so we get coverage whether PostHog is
// reachable or not.
//
// Privacy: the SERVER-side endpoint scrubs email-shaped strings and
// strips URL query strings before logging. The CLIENT here only
// passes the raw error payload through; never reads localStorage,
// never includes auth tokens, never includes form values.

import type { EventName, EventMap } from "./events";

const ENDPOINT = "/api/client-error";

interface SinkExtra {
  kind?: string;
  section?: string;
  componentStack?: string;
  source?: string;
  lineno?: number | string;
  colno?: number | string;
}

function safeMessage(error: unknown): string {
  if (error instanceof Error) return error.message || error.name || "(no message)";
  if (typeof error === "string") return error;
  try { return JSON.stringify(error); } catch { return "(unserialisable error)"; }
}

function safeStack(error: unknown, extra: SinkExtra | undefined): string {
  if (extra?.componentStack) return extra.componentStack;
  if (error instanceof Error && typeof error.stack === "string") return error.stack;
  return "";
}

/**
 * Fire-and-forget POST of the error envelope to /api/client-error.
 *
 * Uses `navigator.sendBeacon` when available (survives page-unload
 * which is exactly when an `Error: chunk load failed` fires). Falls
 * back to `fetch` with `keepalive: true` for the same property.
 * Last-resort fallback is a plain fetch — even if it gets cancelled
 * mid-flight by navigation, the *previous* errors in the same session
 * will already have made it through.
 *
 * Never throws — the error-handling path can't itself produce errors.
 */
export function sendErrorToServer(error: unknown, extra?: SinkExtra): void {
  if (typeof window === "undefined") return;

  const payload = {
    message: safeMessage(error),
    stack: safeStack(error, extra),
    kind: extra?.kind || "unknown",
    section: extra?.section || "",
    componentStack: extra?.componentStack || "",
    source: extra?.source || "",
    lineno: extra?.lineno,
    colno: extra?.colno,
    url: typeof window.location !== "undefined" ? window.location.href : "",
    ua: typeof navigator !== "undefined" ? navigator.userAgent : "",
    ts: Date.now(),
  };

  let json: string;
  try {
    json = JSON.stringify(payload);
  } catch {
    return; // give up — non-serialisable payload can't be sent
  }

  // Best path — sendBeacon: queued by the browser, survives unload,
  // does not block the unload handler. Some browsers cap it at ~64 KB;
  // we truncate aggressively on the server side anyway.
  try {
    if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      const blob = new Blob([json], { type: "application/json" });
      if (navigator.sendBeacon(ENDPOINT, blob)) return;
    }
  } catch {
    /* fall through to fetch */
  }

  // Fetch fallback with keepalive — same survives-unload property,
  // smaller browser support matrix.
  try {
    void fetch(ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: json,
      keepalive: true,
      credentials: "omit",
    }).catch(() => { /* swallow */ });
  } catch {
    /* nothing left to try — error storms shouldn't crash the page */
  }
}

// Type-check: this module is intentionally NOT in events.ts (it's a
// server-side endpoint, not a PostHog event). The import below just
// makes sure the surrounding telemetry types resolve cleanly.
type _Unused = EventName | keyof EventMap;
