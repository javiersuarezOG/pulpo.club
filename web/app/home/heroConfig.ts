// Single source of truth for hero-v3 tunables. Constants live here so
// QA can speed the demo cycle up for screenshot work without hunting
// through component code, and so a future "real number" wire-up has
// a documented home for the fallback values.
//
// Conservative defaults: the cycle interval sits at 7s (mid of the
// 6–8s production band the spec calls out). Faster would feel like an
// arcade; slower would let the user wonder if it's actually live.
//
// Fallback counts: when /data/last_updated.json hasn't resolved yet
// (first ever visit, no cache) we still need to render real-looking
// numbers — never a "—" or a spinner. Source count below mirrors the
// current run-history (7 active scrapers per
// goodlife/oceanside/century21/bienesraices/remax/nexo/encuentra24).
// Listing count is approximate "feels-like" and will be replaced by
// the real total_listings on first successful fetch + persisted via
// the live-counter-cache. Both values update when the pipeline adds
// scrapers; no code change needed.

export const CYCLE_MS_PRODUCTION = 7000;
export const CYCLE_MS_DEMO = 2200;

// Reduce-motion / weak-device fallback: when an FPS measurement on
// mount suggests the device can't keep up, cycle slows further.
// Currently advisory; not yet wired (would require requestAnimationFrame
// sampling on mount). Reserved here for future use.
export const CYCLE_MS_SLOW_DEVICE = 12000;

// Pre-label clay span fallback when source_status is missing.
export const SOURCE_COUNT_FALLBACK = 7;

// LIVE NOW counter fallback when total_listings is missing.
export const LISTING_COUNT_FALLBACK = 910;

// localStorage cache key for live-counter (the only client-cached
// homepage state besides locale + savedIds).
export const LIVE_COUNTER_CACHE_KEY = "pulpo-live-counter-v1";
