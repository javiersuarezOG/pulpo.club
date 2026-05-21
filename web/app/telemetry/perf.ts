/**
 * App-specific perf instrumentation helpers.
 *
 * Wraps `performance.now()` so call sites stay readable. Pairs with the
 * `perf.*` event types in events.ts.
 *
 *   const stop = perfStart();
 *   // ... do work ...
 *   stop("perf.detail_open", { listing_id: id });
 *
 * SSR-safe: when `performance` isn't available we skip the timer +
 * return a no-op stop fn. Keeps the call sites unconditional.
 */
import { track } from "./hook";
import type { EventMap } from "./events";

type PerfEventName =
  | "perf.data_fetch"
  | "perf.filter_recompute"
  | "perf.detail_open"
  | "perf.lightbox_open"
  | "perf.route_transition";

type PerfPayload<K extends PerfEventName> = Omit<EventMap[K], "ms">;

const _now = (): number =>
  typeof performance !== "undefined" && typeof performance.now === "function"
    ? performance.now()
    : Date.now();

/** Start a perf measurement. Returns a `stop(eventName, payload)` fn
 *  that fires the typed event with the elapsed ms appended. */
export function perfStart() {
  const t0 = _now();
  return function stop<K extends PerfEventName>(name: K, payload: PerfPayload<K>): number {
    const ms = Math.round(_now() - t0);
    track(name, { ...payload, ms } as EventMap[K]);
    return ms;
  };
}

/** One-shot timer for fetch() calls. Wraps fetch + emits perf.data_fetch
 *  with the elapsed ms, payload size (bytes), and cache hint when the
 *  Server-Timing header surfaces it. */
export async function timedFetch(
  file: "ranked.json" | "last_updated.json" | "featured.json",
  url: string,
  init?: RequestInit,
): Promise<Response> {
  const stop = perfStart();
  const res = await fetch(url, init);
  // We need to peek the body length for `bytes`, but doing so consumes
  // the response. Clone first so the caller can still call .json().
  const cloned = res.clone();
  let bytes: number | null = null;
  try {
    const txt = await cloned.text();
    bytes = txt.length;
  } catch {
    bytes = null;
  }
  // Server-Timing or X-Vercel-Cache hint when present (Vercel sets it).
  const cacheHeader = res.headers.get("x-vercel-cache") || res.headers.get("cf-cache-status") || "";
  let cache: "hit" | "miss" | "unknown" = "unknown";
  const lc = cacheHeader.toLowerCase();
  if (lc.includes("hit")) cache = "hit";
  else if (lc.includes("miss") || lc.includes("revalidated")) cache = "miss";
  stop("perf.data_fetch", { file, bytes, cache });
  return res;
}

/** PR-perf-5a — instrumented wrapper for /api/* calls.
 *
 *  Reads `Server-Timing: total;dur=<ms>, geo;desc=<region>` from the
 *  response (api/_perf.js#withTiming sets it on every wrapped handler)
 *  and X-Vercel-Region as a backup. Emits perf.api_call with the
 *  endpoint + status + total round-trip ms + server-side ms + region.
 *  Subtracting server_ms from ms gives the network+queue cost — the
 *  budget that the region pin (when we go Pro) closes.
 *
 *  Same contract as fetch(): returns Response. Caller's body-read
 *  flow stays identical (the wrapper doesn't peek the body to avoid
 *  doubling the bandwidth budget for /api/*).
 */
export async function timedApiFetch(
  endpoint: string,
  url: string,
  init?: RequestInit,
): Promise<Response> {
  const t0 = _now();
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    const ms = Math.round(_now() - t0);
    track("perf.api_call", {
      endpoint, status: 0, ms,
      server_ms: null, vercel_region: null,
    });
    throw err;
  }
  const ms = Math.round(_now() - t0);
  const serverTiming = res.headers.get("server-timing") || "";
  const region =
    res.headers.get("x-vercel-region") ||
    extractRegion(serverTiming) ||
    null;
  const server_ms = extractServerMs(serverTiming);
  track("perf.api_call", {
    endpoint,
    status: res.status,
    ms,
    server_ms,
    vercel_region: region,
  });
  return res;
}

function extractServerMs(serverTiming: string): number | null {
  // Format: "total;dur=42, geo;desc=iad1[, ...]" — pick out total's dur.
  const m = serverTiming.match(/total;dur=([0-9.]+)/i);
  if (!m) return null;
  const n = Number.parseFloat(m[1]);
  return Number.isFinite(n) ? Math.round(n) : null;
}

function extractRegion(serverTiming: string): string | null {
  const m = serverTiming.match(/geo;desc=([a-z0-9_-]+)/i);
  return m ? m[1] : null;
}
