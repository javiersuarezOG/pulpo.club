// PostHog client — lazy-loaded via dynamic import inside requestIdleCallback.
// PostHog JS is ~50KB gzipped; not first-paint critical. Autocapture is
// disabled — we have an explicit typed catalog (see events.ts).
//
// Init sequence:
//   1. App renders → useTelemetry() registers a queue
//   2. requestIdleCallback fires → dynamic import('posthog-js')
//   3. PostHog inits, queue drains
//   4. Subsequent track() calls pass through directly
//
// Failure modes are silent: missing API key → tracking is a no-op (dev
// builds, PRs without the env var); offline / blocked by tracker
// extensions → events drop, no errors surface to the user.

import type { EventMap, EventName } from "./events";

type QueuedEvent = {
  name: EventName;
  props: EventMap[EventName];
  ts: number;
};

type PostHog = {
  init: (key: string, opts: Record<string, unknown>) => void;
  capture: (name: string, props?: Record<string, unknown>) => void;
  identify: (id: string, props?: Record<string, unknown>) => void;
  reset: () => void;
  opt_out_capturing: () => void;
  opt_in_capturing: () => void;
  has_opted_out_capturing: () => boolean;
};

let posthog: PostHog | null = null;
const queue: QueuedEvent[] = [];
let initStarted = false;

const POSTHOG_KEY = (import.meta.env.VITE_POSTHOG_KEY as string | undefined) ?? "";
const POSTHOG_HOST = (import.meta.env.VITE_POSTHOG_HOST as string | undefined) ?? "https://eu.i.posthog.com";

// Detect production deploy: only fire telemetry there + on Vercel previews.
// Local `vite dev` stays silent unless explicitly opted in via ?ph=1.
const SHOULD_TELEMETER = (() => {
  if (!POSTHOG_KEY) return false;
  if (typeof window === "undefined") return false;
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.has("ph")) return true;
  } catch { /* ignore */ }
  return !import.meta.env.DEV;
})();

// Read the consent decision recorded by ConsentBanner (pages.jsx). Three
// states: "granted" (full telemetry), "declined" (opt-out before init),
// or "" / unknown (boot-without-decision). Outside the EU the banner
// auto-grants on first paint, so "" only happens for a tiny first-paint
// window before that side-effect lands. We treat "" as granted-pending
// so EU users get queued events flushed once they accept; declined users
// have init replaced with a no-op that wires the opt-out.
function readConsent(): "granted" | "declined" | "" {
  try {
    const v = localStorage.getItem("pulpo-consent") || "";
    if (v === "granted" || v === "declined") return v;
    return "";
  } catch { return ""; }
}

function scheduleInit() {
  if (initStarted) return;
  initStarted = true;
  if (typeof window === "undefined") return;

  // Hard opt-out: if the user explicitly declined we never load the
  // PostHog SDK at all — no init, no session recording, no network
  // request to eu.i.posthog.com. The queue from earlier track() calls
  // is dropped on the floor by every later track() short-circuiting on
  // `posthog == null && !initStarted` (initStarted is true now).
  const consent = readConsent();
  if (consent === "declined") return;

  // Session recording is the heaviest privacy surface — only run it
  // when consent is explicitly granted. EU users with no decision yet
  // ("") still init PostHog so we can capture page-view-class events,
  // but recording stays off until they hit "Accept".
  const recordingEnabled = consent === "granted";

  const start = async () => {
    try {
      const mod = await import("posthog-js");
      posthog = mod.default as unknown as PostHog;
      posthog.init(POSTHOG_KEY, {
        api_host: POSTHOG_HOST,
        autocapture: false,             // explicit catalog only
        // PostHog Web Analytics (Visitors / Pageviews / Sessions / Paths /
        // Channels / Bounce rate / etc.) is hard-coded to $pageview +
        // $pageleave. 'history_change' fires $pageview on cold-load AND
        // every pushState/popstate, which is what the SPA section URLs
        // (/, /browse, /saved, /plans, /account, /listing/:id) need.
        // The custom landing.viewed / route.changed events keep flowing
        // alongside — this is purely additive.
        capture_pageview: "history_change",
        capture_pageleave: true,
        disable_session_recording: !recordingEnabled,
        session_recording: { maskAllInputs: true, sampleRate: 0.1 },
        persistence: "localStorage+cookie",
        loaded: () => drainQueue(),
      });
    } catch (err) {
      // Silent failure; tracking just doesn't happen.
      console.warn("[pulpo] PostHog load failed", err);
    }
  };

  const ric = (window as unknown as { requestIdleCallback?: (cb: () => void) => void }).requestIdleCallback;
  if (typeof ric === "function") {
    ric(() => { void start(); });
  } else {
    setTimeout(() => { void start(); }, 600);
  }
}

function drainQueue() {
  if (!posthog) return;
  while (queue.length) {
    const { name, props } = queue.shift()!;
    try { posthog.capture(name, props as Record<string, unknown>); } catch { /* ignore */ }
  }
}

export function track<K extends EventName>(name: K, props: EventMap[K]) {
  if (!SHOULD_TELEMETER) return;
  if (!posthog) {
    queue.push({ name, props, ts: Date.now() });
    scheduleInit();
    return;
  }
  if (posthog.has_opted_out_capturing && posthog.has_opted_out_capturing()) return;
  try {
    posthog.capture(name, props as Record<string, unknown>);
  } catch { /* ignore */ }
}

export function identify(id: string, props?: Record<string, unknown>) {
  if (!SHOULD_TELEMETER) return;
  if (!posthog) {
    scheduleInit();
    // Identify queue is intentionally not retained — first track() after
    // load identifies via session distinct_id; explicit identify is for
    // post-signup which isn't pre-load anyway.
    return;
  }
  try { posthog.identify(id, props); } catch { /* ignore */ }
}

export function resetIdentity() {
  try { posthog?.reset(); } catch { /* ignore */ }
}

export function optOut() {
  try { posthog?.opt_out_capturing(); } catch { /* ignore */ }
}

export function optIn() {
  try { posthog?.opt_in_capturing(); } catch { /* ignore */ }
}

// Boot the lazy init now so the queue starts draining as soon as the
// browser is idle. Calling this at module import time is fine because
// requestIdleCallback is non-blocking and gracefully no-ops without a key.
if (SHOULD_TELEMETER) scheduleInit();
