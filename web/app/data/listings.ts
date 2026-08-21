// Live-data adapter — fetches the ranked catalog and reshapes each
// record into the Listing schema the rest of the app expects.
//
// The RESHAPING moved to shared/adapt/listing.ts, because /api/v1, the
// MCP tools and the Telegram bot all have to turn the same pipeline
// rows into the same Listing shape — two adapters would mean the bot
// and the website disagree about what a listing is.
//
// What stays here is the part that is genuinely browser-side: the
// fetch, the slim-then-full fallback, and the in-module cache. Note the
// public API deliberately does NOT copy that fallback — ranked.json
// carries broker PII (see api/v1/_catalog.ts).
//
// adaptListing is re-exported below with the active country already
// bound, so every existing call site and test keeps the 1-arg form.

import type { Listing } from "./types";
import { ACTIVE_COUNTRY } from "../config/countries";
import { adaptListing as adaptListingShared } from "../../../shared/adapt/listing";

export { ZONE_NAMES, pretty } from "../../../shared/zones";
export { detectListingLang } from "../../../shared/adapt/listing";

/**
 * Adapt one pipeline row, using the country selected at build time via
 * VITE_PULPO_ACTIVE_COUNTRY. The shared implementation takes the
 * country as a parameter because ACTIVE_COUNTRY resolves through Vite's
 * import.meta.env, which does not exist in a serverless function.
 */
export function adaptListing(raw: any): Listing {
  return adaptListingShared(raw, ACTIVE_COUNTRY);
}

// 60s in-module cache of the adapted catalog. Browser-side only: the
// serverless equivalent is the mtime-keyed cache in api/v1/_catalog.ts,
// which invalidates on a data commit rather than on a clock.
let cache: { ts: number; listings: Listing[] } | null = null;

export async function loadListings(): Promise<Listing[]> {
  // 60s in-memory cache — same listings JSON serves every page load
  // within a session.
  if (cache && Date.now() - cache.ts < 60_000) return cache.listings;

  // PR-photo-nav-perf — instrumented fetch surfaces the data-load
  // latency + cache-hit-rate in PostHog.
  // PR-perf-3b — fetch the slim list-view projection first (~40-60%
  // smaller payload, drops broker contact + validation + raw scraper
  // text + hires sidecar fields that the adapter never reads). Fall
  // back to the full ranked.json on 404 so the client survives the
  // window between this PR landing and the first nightly that emits
  // ranked.list.json. Once the nightly has run, the fallback becomes
  // dead code (file always present); we keep it as a safety net in
  // case the pipeline ever regresses on the slim emit.
  const { timedFetch } = await import("../telemetry/perf");
  const accept = { headers: { Accept: "application/json" } };
  let res: Response | null = null;
  try {
    res = await timedFetch("ranked.list.json", "/data/ranked.list.json", accept);
    if (res.status === 404) res = null;
  } catch {
    // network error / fetch threw → fall through to ranked.json
    res = null;
  }
  if (!res || !res.ok) {
    res = await timedFetch("ranked.json", "/data/ranked.json", accept);
    if (!res.ok) {
      throw new Error(`ranked HTTP ${res.status}`);
    }
  }
  const raw = await res.json();
  if (!Array.isArray(raw)) {
    throw new Error("ranked payload is not an array");
  }
  const listings = raw.map(adaptListing);
  cache = { ts: Date.now(), listings };
  return listings;
}

export function clearListingsCache() {
  cache = null;
}
