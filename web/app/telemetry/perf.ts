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
  file: "ranked.json" | "ranked.list.json" | "last_updated.json" | "featured.json",
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
