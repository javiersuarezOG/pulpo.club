// Global error capture — feeds two sinks in parallel:
//   1. PostHog Error Tracking — funnels, alerts, session replay link.
//   2. /api/client-error → Vercel runtime logs — always-on backstop for
//      when PostHog is blocked (ad-blockers, declined consent, SDK fail).
//
// ErrorBoundary catches render-time throws separately and wires the
// same two sinks (see error-boundary.jsx). Idempotent so HMR /
// StrictMode double-effect doesn't double-register.

import { captureException } from "./client";
import { sendErrorToServer } from "./error-sink";

let booted = false;

export function bootGlobalErrorHandlers() {
  if (booted) return;
  if (typeof window === "undefined") return;
  booted = true;

  window.addEventListener("error", (e) => {
    const err = e.error ?? e.message;
    const extra = {
      source: e.filename,
      lineno: e.lineno,
      colno: e.colno,
      kind: "window.error",
    };
    try { captureException(err, extra); } catch { /* swallow */ }
    try { sendErrorToServer(err, extra); } catch { /* swallow */ }
  });

  window.addEventListener("unhandledrejection", (e) => {
    const extra = { kind: "unhandledrejection" };
    try { captureException(e.reason, extra); } catch { /* swallow */ }
    try { sendErrorToServer(e.reason, extra); } catch { /* swallow */ }
  });
}
