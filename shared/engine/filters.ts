// shared/engine/filters.ts — Pulpo's filter and rank engine.
//
// Moved here VERBATIM from web/app/pages.jsx so that every surface
// filters and ranks identically: the website (which imports this
// in-process and keeps its static-CDN data fetch), /api/v1/listings,
// the MCP tools, and the Telegram bot. One implementation, four
// consumers — a second copy anywhere is the drift this layer exists to
// prevent.
//
// The comments below are the originals, including the ones recording
// why a given default or comparison is the way it is. They are the
// institutional memory of several bugs and are worth more here than a
// tidier rewrite would be.
//
// Behaviour is locked by web/app/engine-characterization.test.ts, which
// was written against the pages.jsx original BEFORE this move and is
// not edited by it.
//
// Platform-neutral by construction: no fs, no process, no window, no
// React. The root tsconfig pins types:[] so a Node global here fails
// the browser typecheck immediately.

import { matchesQuery, tokenize } from "./search";

// Default ranking weights — match legacy index.js (PR-4b restore).
export const WEIGHT_DEFAULTS = { value: 40, location: 35, momentum: 25 };

export function makeDefaultFilters() {
  return {
    zones: new Set(),
    land_types: new Set(),
    features: new Set(),
    infra: new Set(),
    status: new Set(),
    price_min: 0,
    // null = no upper cap. The previous default of 1,000,000 silently
    // hid every listing above $1M (~20% of the catalog) — Browse
    // counted ~700 while LiveStats correctly reported 873. Bug fix.
    price_max: null,
    size_min: 0,
    // null = no upper cap, mirroring price_max. Number inputs accept any
    // value; the 20k m² visual scale is only a legibility choice.
    size_max: null,
    readiness: 0,
    // PR-4b — feature parity with legacy:
    score_min: 0,                             // 0–100 score floor
    weights: { ...WEIGHT_DEFAULTS },          // V/L/M weights, sum = 100
    photos: "all",                            // "all" | "with" | "none"
    // Rewrite Phase 5B — new IA filter axes (Beach/Lake × Homes/
    // Condos/Land + 4 discovery tags). The homepage CategoryGrid /
    // DiscoveryPills navigate here with these pre-set via
    // buildFiltersForCategory.
    master_category: null,                    // "beach" | "lake" | null
    subcategory: null,                        // "homes" | "condos" | "land" | null
    discovery_tags: new Set(),                // subset of {top_rated, under_250k, gated, waterfront}
    rank_max: null,                           // position-rank cap; e.g. 10 for "Top 10" chip
    // Inverse-semantic toggle. Defaults to false → listings where the
    // broker hasn't shared price or size are hidden. Toggling on
    // surfaces them at the bottom of the result set (ranker already
    // hard-floored them, so the order is correct without extra work).
    include_incomplete: false,
    // Free-text exact-lookup search (web/app/lib/search-match.ts). The
    // user types a Pulpo id, broker URL, zone, or title fragment;
    // every whitespace-separated token must hit somewhere in the
    // listing's haystack. Empty = match-all (no-op).
    query: "",
  };
}

// Recompute composite score from V/L/M components and user-overridden
// weights. Mirrors legacy index.js:recomputeComposite. Returns the
// listing's static rank_score when weights match defaults.
export function recomputeComposite(l, w) {
  if (!w) return l.rank_score ?? 0;
  if (w.value === WEIGHT_DEFAULTS.value && w.location === WEIGHT_DEFAULTS.location && w.momentum === WEIGHT_DEFAULTS.momentum) {
    return l.rank_score ?? 0;
  }
  const v = l.value_score ?? 0;
  const ll = l.location_score ?? 0;
  const m = l.momentum_score ?? 0;
  const total = w.value + w.location + w.momentum;
  if (total <= 0) return 0;
  return (v * w.value + ll * w.location + m * w.momentum) / total;
}

// "Top 10" rank map: listing id → 1..10 based on global rank_score desc.
// Filters out sold + missing-rank listings before slicing, so the chip
// represents the 10 best *available* listings rather than the 10
// highest scores including sold/null entries. Same map is consumed by
// BrowsePage and SavedPage so the chip means the same thing on both
// surfaces — and stays attached to the listing regardless of filter
// or sort.
export function buildTopRankMap(listings, n = 10) {
  const out = new Map();
  const ranked = [...listings]
    .filter((l) => !l.is_sold && l.rank_score != null)
    .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0))
    .slice(0, n);
  ranked.forEach((l, i) => out.set(l.id, i + 1));
  return out;
}

// opts.skip ("price" | "size" | undefined) drops that dimension's own
// predicate — used to compute faceted histogram populations that reflect
// every OTHER filter (Airbnb/Amazon convention: a facet excludes its own
// dimension, so interacting with a control can never move its own bars).
// Backward compatible: 2-arg callers (account.jsx) pass no opts.
//
// `opts` is marked optional here because this file is now typechecked
// (it was .jsx before, where arity was never verified). The parameter
// was always effectively optional — the body reads `opts && opts.skip`
// and account.jsx has always called with two arguments. This annotation
// records the real contract; it emits identical JavaScript.
export function applyFilters(listings, f, opts?) {
  const skip = opts && opts.skip;
  // Tokenize once for the whole filter pass — matchesQuery is a hot
  // path (runs per-listing per-render) and re-splitting + re-folding
  // the same query string per row is wasteful.
  const queryTokens = tokenize(f && f.query);
  return listings.filter(l => {
    if (l.is_sold) return false;
    // Quality gate — incomplete listings are hidden by default.
    // The Browse FilterPanel chip flips `include_incomplete` to opt in.
    if (l.is_incomplete && !f.include_incomplete) return false;
    if (f.zones.size && !f.zones.has(l.zone_name)) return false;
    if (f.land_types.size && !f.land_types.has(l.land_type)) return false;
    if (skip !== "price") {
      if (l.price < f.price_min) return false;
      if (f.price_max != null && l.price > f.price_max) return false;
    }
    if (skip !== "size") {
      if (l.size_m2 < f.size_min) return false;
      // null size passes a max-only cap (null > n is false) — identical to
      // the price-null semantics above. Unknown-size listings are still
      // excluded by size_min > 0 (existing behavior; don't "fix").
      if (f.size_max != null && l.size_m2 > f.size_max) return false;
    }
    if (f.features.has("beachfront") && !l.beachfront_tier) return false;
    if (f.features.has("ocean_view") && !l.has_ocean_view) return false;
    if (f.features.has("mountain_view") && !l.has_mountain_view) return false;
    if (f.features.has("flat") && !l.is_flat) return false;
    if (f.features.has("water_body") && !l.has_water_body) return false;
    if (f.infra.has("water") && !l.has_water) return false;
    if (f.infra.has("power") && !l.has_power) return false;
    if (f.infra.has("paved") && l.road_access_type !== "paved") return false;
    if (f.infra.has("sewage") && !l.has_sewage) return false;
    // Mirrors the "motivated" guard below: a null first_seen_date must
    // FAIL the "new" facet, not pass it. `null > 7` is false in JS, so
    // the bare comparison silently kept unknown-age listings in a
    // filter the user asked to narrow to fresh ones.
    if (f.status.has("new") && !(typeof l.first_seen_date === "number" && l.first_seen_date <= 7)) return false;
    if (f.status.has("price_drop") && !l.is_repriced) return false;
    if (f.status.has("off_market") && l.source_type !== "off_market") return false;
    if (f.status.has("motivated") && (typeof l.days_listed !== "number" || l.days_listed < 90)) return false;
    if (l.readiness_score < f.readiness) return false;
    if ((f.score_min ?? 0) > 0 && (l.rank_score ?? 0) < f.score_min) return false;
    if (f.photos === "with" && (l.photos_count ?? 0) === 0) return false;
    if (f.photos === "none" && (l.photos_count ?? 0) > 0) return false;
    // Rewrite Phase 5B — new IA filters. master/sub are single-select;
    // discovery_tags is multi-select (every selected tag must apply).
    if (f.master_category && l.master_category !== f.master_category) return false;
    if (f.subcategory && l.subcategory !== f.subcategory) return false;
    if (f.discovery_tags && f.discovery_tags.size > 0) {
      const tags = Array.isArray(l.discovery_tags) ? l.discovery_tags : [];
      for (const required of f.discovery_tags) {
        if (!tags.includes(required)) return false;
      }
    }
    // Free-text exact-lookup search. Done last because (a) it's the
    // most expensive predicate per row (string concat + substring),
    // and (b) most filtered-out rows never reach this check.
    if (queryTokens.length > 0 && !matchesQuery(l, queryTokens)) return false;
    // rank_max is intentionally NOT applied here — it operates on a
    // position rank that only makes sense AFTER every other predicate
    // has narrowed the set. Callers compute the cap via applyRankCap.
    return true;
  });
}

// Take the post-applyFilters list and, if rank_max is set, keep only the
// top N by rank_score (descending). The N best listings *within the
// current filter scope* — so "Lake + Top 10" means "10 best lake
// listings", not "the global top 10 intersected with lake" (which is
// almost always 0). Listings without a rank_score are dropped from the
// cap to keep the badge consistent with the global Top-10 semantics.
export function applyRankCap(listings, rank_max) {
  if (rank_max == null || rank_max <= 0) return listings;
  return [...listings]
    .filter((l) => l.rank_score != null)
    .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0))
    .slice(0, rank_max);
}
