// localStorage cache for the LIVE NOW counter in the homepage v3 hero.
//
// Why: the hero MUST never show "—" or a spinner in the counter card.
// Per the spec: "use the last loaded number until it loads new." On a
// cold first visit (no cache yet) we fall back to the constants in
// heroConfig.ts; on every subsequent visit we render from cache
// immediately, then update in place when the fresh fetch resolves.
//
// Tiny module — no React, no side effects in the read path. Safe to
// import from any home/* component or test.

import { LIVE_COUNTER_CACHE_KEY } from "../home/heroConfig";

export type LiveCounter = {
  total_listings: number;
  source_count: number;
  /** ISO timestamp the value was fetched; informational, not enforced. */
  fetched_at: string;
};

/** Read the cached value. Returns null on every failure path — missing,
 *  malformed JSON, localStorage disabled (Safari private mode). The
 *  caller falls back to the heroConfig constants. */
export function readLiveCounterCache(): LiveCounter | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LIVE_COUNTER_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      typeof parsed?.total_listings === "number" &&
      typeof parsed?.source_count === "number" &&
      typeof parsed?.fetched_at === "string"
    ) {
      return parsed as LiveCounter;
    }
    return null;
  } catch {
    return null;
  }
}

/** Write the cache. Best-effort — swallow any failure (quota, private
 *  mode, etc.). A failed write means the next visit re-pays the
 *  fallback path, which is fine. */
export function writeLiveCounterCache(value: LiveCounter): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LIVE_COUNTER_CACHE_KEY, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}
