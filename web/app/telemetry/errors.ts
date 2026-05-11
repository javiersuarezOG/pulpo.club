// Global error capture — feeds PostHog's Error Tracking surface for
// exceptions that escape React's render tree (event handlers, async
// callbacks, dynamic imports, top-level script errors). ErrorBoundary
// catches render-time throws separately. Idempotent so HMR / StrictMode
// double-effect doesn't double-register.

import { captureException } from "./client";

let booted = false;

export function bootGlobalErrorHandlers() {
  if (booted) return;
  if (typeof window === "undefined") return;
  booted = true;

  window.addEventListener("error", (e) => {
    captureException(e.error ?? e.message, {
      source: e.filename,
      lineno: e.lineno,
      colno: e.colno,
      kind: "window.error",
    });
  });

  window.addEventListener("unhandledrejection", (e) => {
    captureException(e.reason, { kind: "unhandledrejection" });
  });
}
