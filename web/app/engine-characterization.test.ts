// Characterization suite for Pulpo's filter/rank engine.
//
// WHAT THIS IS FOR
// These functions are about to move out of pages.jsx and into shared/,
// so the website, the /api/v1 endpoints, the MCP tools and the Telegram
// bot all filter and rank identically. pages.jsx is also the file that
// shipped two blank-page crashes, so "move a few hundred lines of it"
// deserves proof rather than confidence.
//
// So this suite is written against the CURRENT implementation, before
// the move, and asserts what the code does today — including behaviour
// that might look like a quirk. After the extraction, pages.jsx
// re-exports from shared/, this file is NOT edited, and it still has to
// pass. That is the whole safety property: an unmodified test file that
// keeps passing across a refactor is evidence the refactor was
// behaviour-preserving.
//
// A note for future editors: if a change makes an assertion here fail,
// the assertion is not automatically wrong — but changing it means
// changing user-visible behaviour on every channel at once. Say so in
// the PR.

import { describe, expect, it } from "vitest";
import {
  applyFilters,
  applyRankCap,
  buildFiltersForCategory,
  buildTopRankMap,
  makeDefaultFilters,
  recomputeComposite,
  WEIGHT_DEFAULTS,
} from "./pages.jsx";

// ── Fixtures ────────────────────────────────────────────────────────
// Synthetic, never web/data: a test bound to real catalog data turns
// any odd nightly into a CI blocker for every unrelated PR.

let seq = 0;
function listing(over: Record<string, any> = {}): any {
  seq += 1;
  return {
    id: `src__${seq}`,
    price: 100_000,
    size_m2: 1000,
    price_per_m2: 100,
    zone_name: "El Tunco",
    land_type: "residential",
    beachfront_tier: null,
    has_ocean_view: false,
    has_mountain_view: false,
    is_flat: false,
    has_water_body: false,
    has_water: false,
    has_power: false,
    has_sewage: false,
    road_access_type: "unknown",
    first_seen_date: 30,
    is_repriced: false,
    source_type: "on_market",
    days_listed: 10,
    readiness_score: 0,
    rank_score: 50,
    value_score: 50,
    location_score: 50,
    momentum_score: 50,
    photos_count: 3,
    master_category: null,
    subcategory: null,
    discovery_tags: [],
    is_sold: false,
    is_incomplete: false,
    ...over,
  };
}

const ids = (rows: any[]) => rows.map((r) => r.id);

function filters(over: Record<string, any> = {}) {
  return { ...makeDefaultFilters(), ...over };
}

// ── Defaults ────────────────────────────────────────────────────────

describe("makeDefaultFilters", () => {
  it("leaves price uncapped by default", () => {
    // Regression guard with history: the previous default of 1,000,000
    // silently hid ~20% of the catalog, so Browse counted ~700 while
    // LiveStats correctly reported 873.
    expect(makeDefaultFilters().price_max).toBeNull();
    expect(makeDefaultFilters().price_min).toBe(0);
  });

  it("hides incomplete listings until explicitly opted into", () => {
    expect(makeDefaultFilters().include_incomplete).toBe(false);
  });

  it("returns fresh Set instances, not shared references", () => {
    // Filters are mutated in place by the UI; a shared Set would leak
    // one page's selections into another's.
    const a = makeDefaultFilters();
    const b = makeDefaultFilters();
    a.zones.add("El Tunco");
    expect(b.zones.size).toBe(0);
    expect(a.weights).not.toBe(b.weights);
  });

  it("starts at the canonical V/L/M weights", () => {
    expect(WEIGHT_DEFAULTS).toEqual({ value: 40, location: 35, momentum: 25 });
    expect(makeDefaultFilters().weights).toEqual(WEIGHT_DEFAULTS);
  });
});

// ── Hard gates ──────────────────────────────────────────────────────

describe("applyFilters — unconditional gates", () => {
  it("always drops sold listings, even when nothing else is filtered", () => {
    const rows = [listing({ id: "a" }), listing({ id: "b", is_sold: true })];
    expect(ids(applyFilters(rows, filters()))).toEqual(["a"]);
  });

  it("drops sold listings even if include_incomplete is on", () => {
    const rows = [listing({ id: "sold", is_sold: true })];
    expect(applyFilters(rows, filters({ include_incomplete: true }))).toEqual([]);
  });

  it("hides incomplete listings by default and reveals them on opt-in", () => {
    const rows = [listing({ id: "ok" }), listing({ id: "partial", is_incomplete: true })];
    expect(ids(applyFilters(rows, filters()))).toEqual(["ok"]);
    expect(ids(applyFilters(rows, filters({ include_incomplete: true })))).toEqual(["ok", "partial"]);
  });

  it("preserves input order — ranking is the caller's job", () => {
    const rows = [listing({ id: "a", rank_score: 1 }), listing({ id: "b", rank_score: 99 })];
    expect(ids(applyFilters(rows, filters()))).toEqual(["a", "b"]);
  });
});

// ── Range predicates ────────────────────────────────────────────────

describe("applyFilters — price and size", () => {
  it("treats price_min/price_max as inclusive bounds", () => {
    const rows = [listing({ id: "lo", price: 50_000 }), listing({ id: "hi", price: 150_000 })];
    expect(ids(applyFilters(rows, filters({ price_min: 50_000, price_max: 150_000 })))).toEqual(["lo", "hi"]);
    expect(ids(applyFilters(rows, filters({ price_min: 50_001 })))).toEqual(["hi"]);
    expect(ids(applyFilters(rows, filters({ price_max: 149_999 })))).toEqual(["lo"]);
  });

  it("null price_max means uncapped, not zero", () => {
    const rows = [listing({ id: "mansion", price: 18_000_000 })];
    expect(ids(applyFilters(rows, filters({ price_max: null })))).toEqual(["mansion"]);
  });

  it("keeps null-priced listings when a maximum is set but drops them at any minimum", () => {
    // Documenting real current behaviour, quirk and all: the comparison
    // is `l.price < f.price_min`, and `null < 0` is false, so a
    // null-priced row survives the default floor of 0 — but any
    // positive floor removes it, while a ceiling never does.
    const rows = [listing({ id: "nullprice", price: null })];
    expect(ids(applyFilters(rows, filters()))).toEqual(["nullprice"]);
    expect(ids(applyFilters(rows, filters({ price_max: 100 })))).toEqual(["nullprice"]);
    expect(applyFilters(rows, filters({ price_min: 1 }))).toEqual([]);
  });

  it("applies size_min as an inclusive floor", () => {
    const rows = [listing({ id: "small", size_m2: 500 }), listing({ id: "big", size_m2: 5000 })];
    expect(ids(applyFilters(rows, filters({ size_min: 5000 })))).toEqual(["big"]);
  });

  it("applies size_max as an inclusive ceiling, null = uncapped", () => {
    const rows = [listing({ id: "small", size_m2: 500 }), listing({ id: "big", size_m2: 5000 })];
    expect(ids(applyFilters(rows, filters({ size_max: null })))).toEqual(["small", "big"]);
    expect(ids(applyFilters(rows, filters({ size_max: 5000 })))).toEqual(["small", "big"]);
    expect(ids(applyFilters(rows, filters({ size_max: 4999 })))).toEqual(["small"]);
  });

  it("keeps null-sized listings under a max-only cap, mirroring price", () => {
    // Same shape as the price quirk above: `null > n` is false, so a
    // ceiling alone keeps unknown-size rows, while any positive floor
    // removes them. Existing behaviour; locked, not fixed.
    const rows = [listing({ id: "nullsize", size_m2: null })];
    expect(ids(applyFilters(rows, filters({ size_max: 1000 })))).toEqual(["nullsize"]);
    expect(applyFilters(rows, filters({ size_min: 1 }))).toEqual([]);
  });
});

describe("applyFilters — faceting via opts.skip", () => {
  // Facet histograms must reflect every OTHER filter but not their own
  // dimension, so that dragging a control can never move its own bars
  // (the Airbnb/Amazon convention). opts.skip drops exactly one
  // dimension's predicate.

  it("skip:'price' ignores the price bounds but honours everything else", () => {
    const rows = [
      listing({ id: "cheap-oceanview", price: 10_000, has_ocean_view: true }),
      listing({ id: "pricey-oceanview", price: 900_000, has_ocean_view: true }),
      listing({ id: "cheap-inland", price: 10_000 }),
    ];
    const f = filters({ price_max: 50_000, features: new Set(["ocean_view"]) });
    expect(ids(applyFilters(rows, f, { skip: "price" }))).toEqual([
      "cheap-oceanview",
      "pricey-oceanview",
    ]);
  });

  it("skip:'size' ignores the size bounds but still honours price", () => {
    const rows = [
      listing({ id: "big-cheap", size_m2: 90_000, price: 10_000 }),
      listing({ id: "big-pricey", size_m2: 90_000, price: 900_000 }),
    ];
    const f = filters({ size_max: 1000, price_max: 50_000 });
    expect(ids(applyFilters(rows, f, { skip: "size" }))).toEqual(["big-cheap"]);
  });

  it("skip never relaxes the sold or incomplete gates", () => {
    const rows = [
      listing({ id: "sold", price: 10_000, is_sold: true }),
      listing({ id: "partial", price: 10_000, is_incomplete: true }),
    ];
    expect(applyFilters(rows, filters({ price_max: 5 }), { skip: "price" })).toEqual([]);
  });

  it("stays backward compatible with 2-arg callers", () => {
    // account.jsx calls applyFilters(listings, f) with no opts.
    const rows = [listing({ id: "a", price: 900_000 })];
    expect(applyFilters(rows, filters({ price_max: 1000 }))).toEqual([]);
    expect(applyFilters(rows, filters({ price_max: 1000 }), undefined)).toEqual([]);
  });
});

// ── Feature / infrastructure flags ──────────────────────────────────

describe("applyFilters — feature and infra flags", () => {
  const cases: [string, string, Record<string, any>][] = [
    ["features", "beachfront", { beachfront_tier: "on_beach" }],
    ["features", "ocean_view", { has_ocean_view: true }],
    ["features", "mountain_view", { has_mountain_view: true }],
    ["features", "flat", { is_flat: true }],
    ["features", "water_body", { has_water_body: true }],
    ["infra", "water", { has_water: true }],
    ["infra", "power", { has_power: true }],
    ["infra", "sewage", { has_sewage: true }],
    ["infra", "paved", { road_access_type: "paved" }],
  ];

  for (const [axis, key, matching] of cases) {
    it(`${axis}:${key} keeps only listings that have it`, () => {
      const rows = [listing({ id: "yes", ...matching }), listing({ id: "no" })];
      expect(ids(applyFilters(rows, filters({ [axis]: new Set([key]) })))).toEqual(["yes"]);
    });
  }

  it("beachfront matches any tier, since the tier is a degree not a boolean", () => {
    const rows = [
      listing({ id: "on", beachfront_tier: "on_beach" }),
      listing({ id: "near", beachfront_tier: "near_beach" }),
      listing({ id: "inland", beachfront_tier: null }),
    ];
    expect(ids(applyFilters(rows, filters({ features: new Set(["beachfront"]) })))).toEqual(["on", "near"]);
  });

  it("requires ALL selected features, not any of them", () => {
    const rows = [
      listing({ id: "both", has_ocean_view: true, is_flat: true }),
      listing({ id: "one", has_ocean_view: true }),
    ];
    expect(ids(applyFilters(rows, filters({ features: new Set(["ocean_view", "flat"]) })))).toEqual(["both"]);
  });

  it("paved requires exactly 'paved' — 'unknown' is not a pass", () => {
    const rows = [
      listing({ id: "paved", road_access_type: "paved" }),
      listing({ id: "gravel", road_access_type: "gravel" }),
      listing({ id: "unknown", road_access_type: "unknown" }),
    ];
    expect(ids(applyFilters(rows, filters({ infra: new Set(["paved"]) })))).toEqual(["paved"]);
  });
});

// ── Status axis ─────────────────────────────────────────────────────

describe("applyFilters — status", () => {
  it("'new' means first seen within 7 days, inclusive", () => {
    const rows = [
      listing({ id: "d0", first_seen_date: 0 }),
      listing({ id: "d7", first_seen_date: 7 }),
      listing({ id: "d8", first_seen_date: 8 }),
    ];
    expect(ids(applyFilters(rows, filters({ status: new Set(["new"]) })))).toEqual(["d0", "d7"]);
  });

  it("'price_drop' keys off is_repriced", () => {
    const rows = [listing({ id: "cut", is_repriced: true }), listing({ id: "same" })];
    expect(ids(applyFilters(rows, filters({ status: new Set(["price_drop"]) })))).toEqual(["cut"]);
  });

  it("'off_market' keys off source_type", () => {
    const rows = [listing({ id: "off", source_type: "off_market" }), listing({ id: "on" })];
    expect(ids(applyFilters(rows, filters({ status: new Set(["off_market"]) })))).toEqual(["off"]);
  });

  it("'motivated' means 90+ days listed and excludes unknown age", () => {
    // null days_listed must not masquerade as a motivated seller —
    // `null >= 90` would be false anyway, but the explicit typeof guard
    // is the behaviour being locked.
    const rows = [
      listing({ id: "d89", days_listed: 89 }),
      listing({ id: "d90", days_listed: 90 }),
      listing({ id: "unknown", days_listed: null }),
    ];
    expect(ids(applyFilters(rows, filters({ status: new Set(["motivated"]) })))).toEqual(["d90"]);
  });
});

// ── Scores, photos, readiness ───────────────────────────────────────

describe("applyFilters — readiness, score floor, photos", () => {
  it("readiness is an inclusive floor", () => {
    const rows = [listing({ id: "r2", readiness_score: 2 }), listing({ id: "r3", readiness_score: 3 })];
    expect(ids(applyFilters(rows, filters({ readiness: 3 })))).toEqual(["r3"]);
  });

  it("score_min only engages above zero and treats null rank_score as zero", () => {
    const rows = [listing({ id: "unscored", rank_score: null }), listing({ id: "scored", rank_score: 80 })];
    expect(ids(applyFilters(rows, filters()))).toEqual(["unscored", "scored"]);
    expect(ids(applyFilters(rows, filters({ score_min: 1 })))).toEqual(["scored"]);
  });

  it("photos 'with' and 'none' partition the catalog", () => {
    const rows = [listing({ id: "has", photos_count: 4 }), listing({ id: "none", photos_count: 0 })];
    expect(ids(applyFilters(rows, filters({ photos: "with" })))).toEqual(["has"]);
    expect(ids(applyFilters(rows, filters({ photos: "none" })))).toEqual(["none"]);
    expect(ids(applyFilters(rows, filters({ photos: "all" })))).toEqual(["has", "none"]);
  });
});

// ── IA axes ─────────────────────────────────────────────────────────

describe("applyFilters — category and discovery tags", () => {
  it("master_category and subcategory are single-select and combine", () => {
    const rows = [
      listing({ id: "bl", master_category: "beach", subcategory: "land" }),
      listing({ id: "bh", master_category: "beach", subcategory: "homes" }),
      listing({ id: "ll", master_category: "lake", subcategory: "land" }),
    ];
    expect(ids(applyFilters(rows, filters({ master_category: "beach" })))).toEqual(["bl", "bh"]);
    expect(ids(applyFilters(rows, filters({ master_category: "beach", subcategory: "land" })))).toEqual(["bl"]);
  });

  it("discovery_tags are AND semantics — every selected tag must apply", () => {
    const rows = [
      listing({ id: "both", discovery_tags: ["top_rated", "gated"] }),
      listing({ id: "one", discovery_tags: ["top_rated"] }),
    ];
    expect(ids(applyFilters(rows, filters({ discovery_tags: new Set(["top_rated", "gated"]) })))).toEqual(["both"]);
  });

  it("survives a listing whose discovery_tags is not an array", () => {
    // The nullable-field crash rule: this reached production as null
    // before, and `.includes` on null is a blank page.
    const rows = [listing({ id: "bad", discovery_tags: null })];
    expect(() => applyFilters(rows, filters({ discovery_tags: new Set(["gated"]) }))).not.toThrow();
    expect(applyFilters(rows, filters({ discovery_tags: new Set(["gated"]) }))).toEqual([]);
  });
});

// ── Query ───────────────────────────────────────────────────────────

describe("applyFilters — free-text query", () => {
  it("an empty query matches everything", () => {
    const rows = [listing({ id: "a" }), listing({ id: "b" })];
    expect(ids(applyFilters(rows, filters({ query: "   " })))).toEqual(["a", "b"]);
  });

  it("requires every token to hit somewhere in the haystack", () => {
    const rows = [
      listing({ id: "a", zone_name: "El Tunco", title: { en: "Ocean view lot", es: "" } }),
      listing({ id: "b", zone_name: "Mizata", title: { en: "Ocean view lot", es: "" } }),
    ];
    expect(ids(applyFilters(rows, filters({ query: "tunco ocean" })))).toEqual(["a"]);
  });

  it("is accent- and case-insensitive", () => {
    const rows = [listing({ id: "a", zone_name: "La Unión" })];
    expect(ids(applyFilters(rows, filters({ query: "la union" })))).toEqual(["a"]);
    expect(ids(applyFilters(rows, filters({ query: "LA UNIÓN" })))).toEqual(["a"]);
  });

  it("does not apply rank_max — that is a separate, post-filter step", () => {
    // rank_max operates on a position rank that only means anything
    // once every other predicate has narrowed the set.
    const rows = [listing({ id: "a", rank_score: 10 }), listing({ id: "b", rank_score: 90 })];
    expect(ids(applyFilters(rows, filters({ rank_max: 1 })))).toEqual(["a", "b"]);
  });
});

// ── Rank cap ────────────────────────────────────────────────────────

describe("applyRankCap", () => {
  it("is a no-op when unset or non-positive", () => {
    const rows = [listing({ id: "a" }), listing({ id: "b" })];
    expect(applyRankCap(rows, null)).toBe(rows);
    expect(applyRankCap(rows, 0)).toBe(rows);
  });

  it("keeps the N best WITHIN the current filter scope", () => {
    // "Lake + Top 10" must mean "the 10 best lake listings", not "the
    // global top 10 intersected with lake" (which is nearly always 0).
    const rows = [
      listing({ id: "mid", rank_score: 50 }),
      listing({ id: "best", rank_score: 90 }),
      listing({ id: "worst", rank_score: 10 }),
    ];
    expect(ids(applyRankCap(rows, 2))).toEqual(["best", "mid"]);
  });

  it("drops unscored listings from the cap", () => {
    const rows = [listing({ id: "scored", rank_score: 10 }), listing({ id: "unscored", rank_score: null })];
    expect(ids(applyRankCap(rows, 5))).toEqual(["scored"]);
  });

  it("does not mutate its input", () => {
    const rows = [listing({ id: "a", rank_score: 1 }), listing({ id: "b", rank_score: 2 })];
    applyRankCap(rows, 1);
    expect(ids(rows)).toEqual(["a", "b"]);
  });
});

// ── Composite re-scoring ────────────────────────────────────────────

describe("recomputeComposite", () => {
  it("short-circuits to the pipeline's rank_score at default weights", () => {
    // Not just an optimisation: the pipeline's score includes a quality
    // leg the client cannot reproduce, so recomputing at defaults would
    // silently change the ordering.
    const l = listing({ rank_score: 85.5, value_score: 0, location_score: 0, momentum_score: 0 });
    expect(recomputeComposite(l, { ...WEIGHT_DEFAULTS })).toBe(85.5);
  });

  it("falls back to rank_score when weights are absent", () => {
    expect(recomputeComposite(listing({ rank_score: 42 }), null)).toBe(42);
    expect(recomputeComposite(listing({ rank_score: null }), null)).toBe(0);
  });

  it("computes a weighted mean once weights are customised", () => {
    const l = listing({ value_score: 100, location_score: 0, momentum_score: 0, rank_score: 1 });
    expect(recomputeComposite(l, { value: 100, location: 0, momentum: 0 })).toBe(100);
    expect(recomputeComposite(l, { value: 50, location: 50, momentum: 0 })).toBe(50);
  });

  it("treats null component scores as zero rather than throwing", () => {
    const l = listing({ value_score: null, location_score: null, momentum_score: null });
    expect(recomputeComposite(l, { value: 100, location: 0, momentum: 0 })).toBe(0);
  });

  it("returns 0 for a zero weight total instead of dividing by zero", () => {
    const l = listing({ value_score: 100 });
    expect(recomputeComposite(l, { value: 0, location: 0, momentum: 0 })).toBe(0);
  });
});

// ── Top-10 map ──────────────────────────────────────────────────────

describe("buildTopRankMap", () => {
  it("maps the best N listing ids to 1-based positions", () => {
    const rows = [
      listing({ id: "c", rank_score: 10 }),
      listing({ id: "a", rank_score: 90 }),
      listing({ id: "b", rank_score: 50 }),
    ];
    const map = buildTopRankMap(rows, 2);
    expect(map.get("a")).toBe(1);
    expect(map.get("b")).toBe(2);
    expect(map.has("c")).toBe(false);
  });

  it("excludes sold and unscored listings so the badge means 'best available'", () => {
    const rows = [
      listing({ id: "sold", rank_score: 99, is_sold: true }),
      listing({ id: "unscored", rank_score: null }),
      listing({ id: "real", rank_score: 20 }),
    ];
    expect([...buildTopRankMap(rows, 10).keys()]).toEqual(["real"]);
  });

  it("defaults to a top-10 window", () => {
    const rows = Array.from({ length: 15 }, (_, i) => listing({ id: `l${i}`, rank_score: i }));
    expect(buildTopRankMap(rows).size).toBe(10);
  });

  it("does not mutate its input", () => {
    const rows = [listing({ id: "a", rank_score: 1 }), listing({ id: "b", rank_score: 2 })];
    buildTopRankMap(rows);
    expect(ids(rows)).toEqual(["a", "b"]);
  });
});

// ── Category slug map ───────────────────────────────────────────────

describe("buildFiltersForCategory", () => {
  it("returns untouched defaults for null and for unknown slugs", () => {
    // An unknown slug must not throw and must not silently filter —
    // these come straight from a user-editable ?cat= query param.
    expect(buildFiltersForCategory(null)).toEqual(makeDefaultFilters());
    expect(buildFiltersForCategory("does-not-exist")).toEqual(makeDefaultFilters());
  });

  it("maps feature and status slugs onto the right axis", () => {
    expect(buildFiltersForCategory("beachfront").features.has("beachfront")).toBe(true);
    expect(buildFiltersForCategory("flat_buildable").features.has("flat")).toBe(true);
    expect(buildFiltersForCategory("new_this_week").status.has("new")).toBe(true);
    expect(buildFiltersForCategory("motivated_sellers").status.has("motivated")).toBe(true);
    expect(buildFiltersForCategory("commercial").land_types.has("commercial")).toBe(true);
  });

  it("maps price and readiness slugs onto scalars", () => {
    expect(buildFiltersForCategory("under_100k").price_max).toBe(100_000);
    expect(buildFiltersForCategory("under_50k").price_max).toBe(50_000);
    expect(buildFiltersForCategory("build_ready").readiness).toBe(3);
  });

  it("maps the IA grid slugs to master/sub pairs", () => {
    const f = buildFiltersForCategory("beach_condos");
    expect(f.master_category).toBe("beach");
    expect(f.subcategory).toBe("condos");
    expect(buildFiltersForCategory("lake").master_category).toBe("lake");
    expect(buildFiltersForCategory("lake").subcategory).toBeNull();
  });

  it("adds rank_max=10 to the shelf 'view all' slugs, matching the shelf promise", () => {
    for (const slug of [
      "top_beach_terrenos", "top_beach_condos", "top_beach_homes",
      "top_lake_terrenos", "top_lake_condos", "top_lake_homes",
    ]) {
      expect(buildFiltersForCategory(slug).rank_max, slug).toBe(10);
    }
    expect(buildFiltersForCategory("top_10").rank_max).toBe(10);
  });

  it("maps discovery pills to tags", () => {
    for (const tag of ["top_rated", "under_250k", "gated", "waterfront"]) {
      expect(buildFiltersForCategory(tag).discovery_tags.has(tag), tag).toBe(true);
    }
  });

  it("lands HeroV5 destination cards on their master category", () => {
    expect(buildFiltersForCategory("surf_city_1").master_category).toBe("beach");
    expect(buildFiltersForCategory("coatepeque").master_category).toBe("lake");
    expect(buildFiltersForCategory("ilopango").master_category).toBe("lake");
  });
});

// ── Composition ─────────────────────────────────────────────────────

describe("filter → cap composition", () => {
  it("caps within the filtered scope, which is the point of the two-step", () => {
    const rows = [
      listing({ id: "lake-best", master_category: "lake", rank_score: 40 }),
      listing({ id: "lake-2nd", master_category: "lake", rank_score: 30 }),
      listing({ id: "beach-top", master_category: "beach", rank_score: 99 }),
    ];
    const f = filters({ master_category: "lake", rank_max: 1 });
    // Naively intersecting a global top-1 with "lake" would yield [].
    expect(ids(applyRankCap(applyFilters(rows, f), f.rank_max))).toEqual(["lake-best"]);
  });
});
