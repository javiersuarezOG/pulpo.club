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
  captureException: (error: unknown, extra?: Record<string, unknown>) => void;
  identify: (id: string, props?: Record<string, unknown>) => void;
  reset: () => void;
  opt_out_capturing: () => void;
  opt_in_capturing: () => void;
  has_opted_out_capturing: () => boolean;
  isFeatureEnabled: (key: string) => boolean | undefined;
  onFeatureFlags: (cb: () => void) => void;
  get_distinct_id?: () => string | undefined;
};

type QueuedException = { error: unknown; extra?: Record<string, unknown>; ts: number };

let posthog: PostHog | null = null;
const queue: QueuedEvent[] = [];
const exceptionQueue: QueuedException[] = [];
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

// Allow-list of query parameters permitted to flow through to PostHog on
// any URL-bearing event property. Anything not in this set is stripped
// before send. Conservative by design: when adding a new param, weigh
// whether it could ever carry PII (auth tokens, emails, OTPs, session
// IDs) before adding. The cold-load $pageview fires BEFORE app.jsx gets
// a chance to replaceState the URL clean, so without this scrubber a
// visit to /?email=foo leaks the email into PostHog's $current_url.
const URL_PARAM_ALLOWLIST = new Set([
  // Marketing attribution — preserved for funnel analysis.
  "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
  "ref", "gclid", "fbclid",
  // Locale.
  "lang",
  // Browse filter state (must round-trip for funnel analysis).
  "cat", "sort",
  "pmin", "pmax", "smin", "ready", "score_min",
  "wv", "wl", "wm",
  "zones", "types", "features", "infra", "status",
  // Dev tooling.
  "dev", "debug", "ph",
]);

// Event properties that carry a URL or path+search string. Scrubbed
// against URL_PARAM_ALLOWLIST in before_send.
const URL_PROPS_TO_SCRUB: readonly string[] = [
  // PostHog auto-populated.
  "$current_url", "$initial_current_url",
  "$referrer", "$initial_referrer",
  "$pathname",
  // Custom pulpo properties (see route.changed in events.ts).
  "from_path", "to_path",
];

function scrubUrl(input: unknown): unknown {
  if (typeof input !== "string" || input.length === 0) return input;
  let url: URL;
  try {
    // Use a throwaway base so relative paths parse. We only return the
    // original origin if the caller passed a fully-qualified URL.
    url = new URL(input, "https://pulpo.club");
  } catch {
    return input;
  }
  const toDelete: string[] = [];
  url.searchParams.forEach((_value, key) => {
    if (!URL_PARAM_ALLOWLIST.has(key)) toDelete.push(key);
  });
  for (const key of toDelete) url.searchParams.delete(key);
  if (!/^https?:\/\//i.test(input)) {
    return `${url.pathname}${url.search}${url.hash}`;
  }
  return url.toString();
}

function scrubEventUrls(event: { properties?: Record<string, unknown> } | null | undefined) {
  if (!event || !event.properties) return event;
  for (const prop of URL_PROPS_TO_SCRUB) {
    if (prop in event.properties) {
      event.properties[prop] = scrubUrl(event.properties[prop]);
    }
  }
  return event;
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
        // Scrub URL-bearing properties against the param allow-list
        // before sending. Catches the cold-load $pageview window where
        // app.jsx's replaceState hasn't run yet to clean a /?email=…
        // entry URL.
        before_send: scrubEventUrls,
        loaded: () => {
          drainQueue();
          // Subscribe to feature-flag arrival so React consumers can
          // re-render once values are known. PostHog calls this on the
          // first flag load AND on subsequent reloads; we only need to
          // signal once, so de-dupe with the flagsLoaded sentinel.
          try {
            posthog?.onFeatureFlags(() => {
              if (!flagsLoaded) notifyFlagsLoaded();
            });
          } catch { /* ignore */ }
        },
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
  while (exceptionQueue.length) {
    const { error, extra } = exceptionQueue.shift()!;
    try { posthog.captureException(error, extra); } catch { /* ignore */ }
  }
}

// Test-mode capture hook (rewrite Phase 8). When the URL carries
// `?posthog_capture=1` we ALSO push every track() call to a
// window-attached buffer so Playwright specs can assert the right
// events fired without needing real PostHog network round-trips or
// a fake POSTHOG_KEY. The flag is opt-in per request, never reads
// in production unless the URL explicitly includes the param —
// production traffic shouldn't carry it.
const TEST_CAPTURE_ENABLED = (() => {
  try {
    if (typeof window === "undefined") return false;
    return new URLSearchParams(window.location.search).has("posthog_capture");
  } catch { return false; }
})();
function testModePush(name: string, props: unknown) {
  if (!TEST_CAPTURE_ENABLED) return;
  if (typeof window === "undefined") return;
  const w = window as unknown as { __pulpoEvents__?: Array<{ name: string; props: unknown; ts: number }> };
  if (!Array.isArray(w.__pulpoEvents__)) w.__pulpoEvents__ = [];
  w.__pulpoEvents__.push({ name, props, ts: Date.now() });
}

export function track<K extends EventName>(name: K, props: EventMap[K]) {
  testModePush(name, props);
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

// Exception capture — feeds PostHog's Error Tracking surface (emits a
// native $exception event). Called from ErrorBoundary.componentDidCatch
// and the global window.onerror / unhandledrejection handlers in
// telemetry/errors.ts. Queues like track() so exceptions fired before
// the SDK has loaded still land once init completes.
export function captureException(error: unknown, extra?: Record<string, unknown>) {
  if (!SHOULD_TELEMETER) return;
  if (!posthog) {
    exceptionQueue.push({ error, extra, ts: Date.now() });
    scheduleInit();
    return;
  }
  if (posthog.has_opted_out_capturing && posthog.has_opted_out_capturing()) return;
  try { posthog.captureException(error, extra); } catch { /* ignore */ }
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

// Returns the current anonymous PostHog distinct_id, or null if the SDK
// hasn't loaded yet (which is normal during the deferred-init window).
// Used by the Stripe checkout helpers to propagate the anon session ID
// through to the server webhook so post-payment events stitch into the
// same person_id as the pre-payment client events.
export function getDistinctId(): string | null {
  if (!posthog) return null;
  try {
    const id = posthog.get_distinct_id?.();
    return typeof id === "string" && id.length > 0 ? id : null;
  } catch {
    return null;
  }
}

export function optOut() {
  try { posthog?.opt_out_capturing(); } catch { /* ignore */ }
}

export function optIn() {
  try { posthog?.opt_in_capturing(); } catch { /* ignore */ }
}

// ── Feature flags ────────────────────────────────────────────────────
//
// Boolean PostHog feature flags. Used by Wave-1 CTA routing for runtime
// kill-switch capability — flip the flag in PostHog (rollout 100% → 0%)
// to revert behavior without a deploy.
//
// PostHog loads flags asynchronously after init; before they arrive,
// callers receive `fallback`. Subscribers via `onFeatureFlagsLoaded`
// are notified once at first load so React hooks can re-render.

const flagsLoadedSubs = new Set<() => void>();
let flagsLoaded = false;

function notifyFlagsLoaded() {
  flagsLoaded = true;
  for (const cb of flagsLoadedSubs) {
    try { cb(); } catch { /* ignore */ }
  }
}

export function isFeatureEnabled(key: string, fallback: boolean): boolean {
  if (!posthog) return fallback;
  try {
    const v = posthog.isFeatureEnabled(key);
    if (typeof v === "boolean") return v;
    return fallback;
  } catch {
    return fallback;
  }
}

export function onFeatureFlagsLoaded(cb: () => void): () => void {
  if (flagsLoaded) {
    // Already loaded — fire async so subscribers don't run synchronously
    // inside their own setup effect.
    setTimeout(() => { try { cb(); } catch { /* ignore */ } }, 0);
    return () => {};
  }
  flagsLoadedSubs.add(cb);
  return () => { flagsLoadedSubs.delete(cb); };
}

// Boot the lazy init now so the queue starts draining as soon as the
// browser is idle. Calling this at module import time is fine because
// requestIdleCallback is non-blocking and gracefully no-ops without a key.
if (SHOULD_TELEMETER) scheduleInit();
