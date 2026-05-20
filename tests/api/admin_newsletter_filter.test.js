// Unit tests for api/admin/newsletter/_filter.js — Node port of
// automation/newsletter/segments.py. The two implementations must agree
// on selection behavior; this spec covers the conjunctive-across-axes
// + disjunctive-within-axis semantics + category predicates + price band.
//
// If you touch automation/newsletter/segments.py, mirror the change here
// and add a regression row below.

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// CJS module under api/ — destructure off the default export so the
// vitest ESM→CJS interop is unambiguous (matches the pattern in
// tests/api/nightly_health.test.js).
import filterModule from "../../api/admin/newsletter/_filter.js";
const {
  normalizePreference, applyPreference, selectPicks,
  CATEGORY_PREDICATES, NEWSLETTER_COHORTS,
} = filterModule;

// ── Drift guard: Node port vs Python source of truth ─────────────────
// Reads automation/newsletter/segments.py as text and asserts every key
// declared in the Python CATEGORY_PREDICATES dict has a matching key in
// the JS port. The Python file is the canonical pipeline; if these
// diverge the admin widget will silently filter wrong vs production.
function pythonCategoryKeys() {
  const path = resolve(__dirname, "../../automation/newsletter/segments.py");
  const src = readFileSync(path, "utf8");
  // Locate the CATEGORY_PREDICATES = {...} block, then grep keys from it.
  const m = src.match(/CATEGORY_PREDICATES\s*=\s*\{([\s\S]*?)\n\}/);
  if (!m) throw new Error("Could not locate CATEGORY_PREDICATES in segments.py");
  // Each entry is `    "key": lambda …` — grab the string keys.
  return Array.from(m[1].matchAll(/"([a-z_0-9]+)"\s*:/g)).map((row) => row[1]).sort();
}

// Compact builder: produce a listing with sensible defaults so each test
// can override only the fields it cares about.
function mk(overrides = {}) {
  return {
    source: "fixture",
    source_id: String(overrides.id ?? Math.random()),
    rank: 1,
    department: "La Libertad",
    zone: "el-zonte",
    property_type: "land",
    price_usd: 100_000,
    title: "Test plot",
    title_canonical: { en: "Test plot", es: "Lote de prueba" },
    photo_urls: [],
    ...overrides,
  };
}

describe("normalizePreference", () => {
  it("coerces missing input into an empty preference", () => {
    expect(normalizePreference(undefined)).toEqual({
      zones: [], departments: [], property_types: [], categories: [],
      min_price_usd: null, max_price_usd: null,
    });
  });

  it("strips non-string entries from list axes + non-finite numbers from price", () => {
    expect(normalizePreference({
      zones: ["a", 7, null, "b"],
      departments: ["La Libertad"],
      max_price_usd: "200000",          // string → null (not coerced)
      min_price_usd: Number.NaN,
    })).toMatchObject({
      zones: ["a", "b"],
      departments: ["La Libertad"],
      max_price_usd: null,
      min_price_usd: null,
    });
  });
});

describe("applyPreference — axis semantics", () => {
  const pool = [
    mk({ id: "1", zone: "el-zonte",  department: "La Libertad", property_type: "land", price_usd: 80_000 }),
    mk({ id: "2", zone: "el-tunco",  department: "La Libertad", property_type: "house", price_usd: 250_000 }),
    mk({ id: "3", zone: "ahuachapan", department: "Ahuachapán", property_type: "land", price_usd: 30_000 }),
    mk({ id: "4", zone: "el-zonte",  department: "La Libertad", property_type: "condo", price_usd: 180_000 }),
  ];

  it("empty preference passes everything through", () => {
    const out = applyPreference(pool, normalizePreference({}));
    expect(out).toHaveLength(pool.length);
  });

  it("zones filter is disjunctive within axis", () => {
    const out = applyPreference(pool, normalizePreference({ zones: ["el-zonte", "el-tunco"] }));
    expect(out.map((l) => l.source_id).sort()).toEqual(["1", "2", "4"]);
  });

  it("departments filter is case-insensitive (matches segments.py)", () => {
    const out = applyPreference(pool, normalizePreference({ departments: ["la libertad"] }));
    expect(out.map((l) => l.source_id).sort()).toEqual(["1", "2", "4"]);
  });

  it("price band is inclusive of min, exclusive on max>x", () => {
    const out = applyPreference(pool, normalizePreference({ min_price_usd: 60_000, max_price_usd: 200_000 }));
    expect(out.map((l) => l.source_id).sort()).toEqual(["1", "4"]);
  });

  it("axes combine conjunctively (AND across departments + property_type)", () => {
    const out = applyPreference(pool, normalizePreference({
      departments: ["La Libertad"], property_types: ["land", "condo"],
    }));
    expect(out.map((l) => l.source_id).sort()).toEqual(["1", "4"]);
  });
});

describe("CATEGORY_PREDICATES — drift guard", () => {
  it("Node port has the same keys as Python segments.py", () => {
    const nodeKeys = Object.keys(CATEGORY_PREDICATES).sort();
    expect(nodeKeys).toEqual(pythonCategoryKeys());
  });
});

describe("NEWSLETTER_COHORTS — drift guard", () => {
  // Read the TS constants file as text and assert the JS-side list in
  // _filter.js matches it. The pytest counterpart asserts the TS file
  // matches the Python Cohort literal — transitively, all three sides
  // (Python types.py → TS constants.ts → JS _filter.js) stay in lockstep.
  function tsCohortKeys() {
    const path = resolve(__dirname, "../../web/app/admin/widgets/newsletter/constants.ts");
    const src = readFileSync(path, "utf8");
    const m = src.match(/const\s+NEWSLETTER_COHORTS\s*=\s*\[([\s\S]*?)\]\s*as\s+const/);
    if (!m) throw new Error("Could not locate NEWSLETTER_COHORTS in constants.ts");
    return Array.from(m[1].matchAll(/"([a-z_]+)"/g)).map((row) => row[1]).sort();
  }

  it("Node _filter.js NEWSLETTER_COHORTS matches TS constants.ts", () => {
    expect([...NEWSLETTER_COHORTS].sort()).toEqual(tsCohortKeys());
  });
});

describe("CATEGORY_PREDICATES — invariants", () => {
  it("beachfront includes walk-to-beach", () => {
    expect(CATEGORY_PREDICATES.beachfront(mk({ is_walk_to_beach: true }))).toBe(true);
    expect(CATEGORY_PREDICATES.beachfront(mk({ is_beachfront: true }))).toBe(true);
    expect(CATEGORY_PREDICATES.beachfront(mk({}))).toBe(false);
  });

  it("build_ready requires power AND water", () => {
    expect(CATEGORY_PREDICATES.build_ready(mk({ has_power: true, has_water: true }))).toBe(true);
    expect(CATEGORY_PREDICATES.build_ready(mk({ has_power: true }))).toBe(false);
  });

  it("under_50k uses price_usd as the predicate input", () => {
    expect(CATEGORY_PREDICATES.under_50k(mk({ price_usd: 30_000 }))).toBe(true);
    expect(CATEGORY_PREDICATES.under_50k(mk({ price_usd: 50_000 }))).toBe(false);
    expect(CATEGORY_PREDICATES.under_50k(mk({ price_usd: null }))).toBe(false);
  });
});

describe("applyPreference + categories", () => {
  const pool = [
    mk({ id: "a", price_usd: 30_000, is_walk_to_beach: true, has_power: true, has_water: true }),
    mk({ id: "b", price_usd: 90_000, has_power: true, has_water: true }),
    mk({ id: "c", price_usd: 30_000 }),
  ];

  it("requires ALL categories to match (within-axis AND, mirrors segments.py)", () => {
    const out = applyPreference(pool, normalizePreference({ categories: ["under_50k", "build_ready"] }));
    expect(out.map((l) => l.source_id)).toEqual(["a"]);
  });
});

describe("selectPicks", () => {
  it("returns at most top_n, in input order (caller pre-sorts by rank)", () => {
    const pool = Array.from({ length: 15 }, (_, i) => mk({ id: String(i), rank: i + 1 }));
    const { kept, skipCandidates } = selectPicks(pool, 10);
    expect(kept.map((l) => l.source_id)).toEqual(["0","1","2","3","4","5","6","7","8","9"]);
    // Skip candidates need to be stale (>=90 DOM) OR low data quality.
    // None set in fixture → empty.
    expect(skipCandidates).toEqual([]);
  });

  it("surfaces stale listings outside the cut as skip candidates", () => {
    const pool = [
      ...Array.from({ length: 10 }, (_, i) => mk({ id: String(i), rank: i + 1 })),
      mk({ id: "stale", rank: 11, days_listed: 120 }),
      mk({ id: "low-quality", rank: 12, data_quality_score: 0.3 }),
    ];
    const { skipCandidates } = selectPicks(pool, 10);
    expect(skipCandidates.map((l) => l.source_id).sort()).toEqual(["low-quality", "stale"]);
  });
});
