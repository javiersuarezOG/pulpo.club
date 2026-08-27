// GET /api/v1/meta — query vocabulary for channel adapters.
//
// Every fixture below is synthetic. These specs must never read
// web/data: a test bound to real catalog data turns any odd nightly
// into a CI blocker for every unrelated PR (the social-floor
// precedent), and it would make the counts assertions untestable.

import { afterEach, describe, expect, it } from "vitest";
import handler, { buildMeta } from "../../api/v1/meta.js";
import { __testing__, catalogFilename, resolveCountry } from "../../api/v1/_catalog.js";

// Use the seam the HANDLER exposes so the override lands on the same
// module instance the handler reads (ESM import + CJS require of the
// same file can otherwise yield two instances).
const seam = handler.__catalogTesting__ ?? __testing__;

function mockRes() {
  return {
    statusCode: 200,
    headers: {},
    body: null,
    setHeader(k, v) { this.headers[k] = v; return this; },
    status(code) { this.statusCode = code; return this; },
    json(payload) { this.body = payload; return this; },
  };
}

function mockReq(query = {}, overrides = {}) {
  return {
    method: "GET",
    query,
    // Unique-ish IP per call so the module-level limiter cannot make
    // one test's traffic fail another's.
    headers: { "x-forwarded-for": `203.0.113.${Math.floor(Math.random() * 200) + 1}` },
    ...overrides,
  };
}

const row = (over = {}) => ({
  source: "remax",
  source_id: "1",
  zone: "el-tunco",
  master_category: "beach",
  subcategory: "land",
  discovery_tags: ["top_rated"],
  price_usd: 60000,
  area_m2: 1200,
  is_sold: false,
  is_incomplete: false,
  ...over,
});

const catalog = (rows, generatedAt = "2026-08-21T04:04:32.112201+00:00") => ({
  rows,
  generatedAt,
  country: "SV",
});

afterEach(() => seam.reset());

describe("country resolution", () => {
  it("defaults to SV when absent or empty", () => {
    expect(resolveCountry(undefined)).toBe("SV");
    expect(resolveCountry("")).toBe("SV");
  });

  it("is case-insensitive and tolerates array-valued query params", () => {
    expect(resolveCountry("sv")).toBe("SV");
    expect(resolveCountry([" Sv "])).toBe("SV");
  });

  it("rejects unsupported countries instead of silently serving SV", () => {
    // PA data exists on disk but carries El Salvador departments on
    // Panamanian rows; serving it would publish known-wrong geography.
    for (const bad of ["PA", "US", "XX", "'; DROP", "S"]) {
      expect(resolveCountry(bad)).toBeNull();
    }
  });

  it("maps SV to the legacy un-suffixed filename that actually exists", () => {
    // ranked.list.SV.json is never written — asking for it would 503
    // the entire API.
    expect(catalogFilename("SV")).toBe("ranked.list.json");
  });
});

describe("buildMeta", () => {
  it("excludes sold and incomplete rows from every count", () => {
    const meta = buildMeta(catalog([
      row({ source_id: "1" }),
      row({ source_id: "2", is_sold: true }),
      row({ source_id: "3", is_incomplete: true }),
    ]));

    // A channel that shows "El Tunco (3)" and then returns 1 result has
    // lied to the user — counts must match what /listings would serve.
    expect(meta.total).toBe(1);
    expect(meta.zones).toEqual([{ slug: "el-tunco", name: "El Tunco", count: 1 }]);
  });

  it("labels zones with display names and falls back for unknown slugs", () => {
    const meta = buildMeta(catalog([
      row({ source_id: "1", zone: "el-tunco" }),
      row({ source_id: "2", zone: "el-tunco" }),
      row({ source_id: "3", zone: "playa-las-tunas" }),
    ]));

    // Known slug → curated name; unknown slug → Title Case, never a raw
    // slug (the pipeline mints new slugs from broker text constantly).
    expect(meta.zones).toEqual([
      { slug: "el-tunco", name: "El Tunco", count: 2 },
      { slug: "playa-las-tunas", name: "Playa Las Tunas", count: 1 },
    ]);
  });

  it("sorts zones by count desc, then alphabetically for stable output", () => {
    const meta = buildMeta(catalog([
      row({ source_id: "1", zone: "mizata" }),
      row({ source_id: "2", zone: "el-zonte" }),
      row({ source_id: "3", zone: "el-cuco" }),
      row({ source_id: "4", zone: "el-cuco" }),
    ]));
    expect(meta.zones.map((z) => z.slug)).toEqual(["el-cuco", "el-zonte", "mizata"]);
  });

  it("skips null/absent categorical values rather than counting them", () => {
    const meta = buildMeta(catalog([
      row({ source_id: "1", master_category: "beach" }),
      row({ source_id: "2", master_category: null }),
      row({ source_id: "3" }),
    ]));
    // 1096 of 1849 production rows have a null master_category; a
    // "null (1096)" button would be nonsense.
    expect(meta.master_categories).toEqual([{ value: "beach", count: 2 }]);
  });

  it("flattens discovery_tags across rows", () => {
    const meta = buildMeta(catalog([
      row({ source_id: "1", discovery_tags: ["top_rated", "under_250k"] }),
      row({ source_id: "2", discovery_tags: ["under_250k"] }),
      row({ source_id: "3", discovery_tags: null }),
    ]));
    expect(meta.discovery_tags).toEqual([
      { value: "under_250k", count: 2 },
      { value: "top_rated", count: 1 },
    ]);
  });

  it("reports price and size bounds over usable numbers only", () => {
    const meta = buildMeta(catalog([
      row({ source_id: "1", price_usd: 60000, area_m2: 1200 }),
      row({ source_id: "2", price_usd: 950000, area_m2: 45 }),
      row({ source_id: "3", price_usd: null, area_m2: null }),
    ]));
    expect(meta.price_usd).toEqual({ min: 60000, max: 950000 });
    expect(meta.size_m2).toEqual({ min: 45, max: 1200 });
  });

  it("returns null bounds when nothing usable is present", () => {
    // null, not {min:0,max:0} — a channel must be able to tell "no
    // data" from "everything is free".
    const meta = buildMeta(catalog([row({ price_usd: null, area_m2: null })]));
    expect(meta.price_usd).toBeNull();
    expect(meta.size_m2).toBeNull();
  });

  it("passes the pipeline timestamp through and never fabricates one", () => {
    expect(buildMeta(catalog([row()], null)).generated_at).toBeNull();
    expect(buildMeta(catalog([row()])).generated_at).toBe("2026-08-21T04:04:32.112201+00:00");
  });
});

describe("GET /api/v1/meta", () => {
  it("serves the vocabulary with a CDN cache header", () => {
    seam.setCatalog("SV", catalog([row(), row({ source_id: "2", zone: "mizata" })]));
    const res = mockRes();
    handler(mockReq(), res);

    expect(res.statusCode).toBe(200);
    expect(res.body.country).toBe("SV");
    expect(res.body.total).toBe(2);
    expect(res.body.zones).toHaveLength(2);
    // s-maxage does the work: data changes once nightly, so the CDN
    // absorbs traffic and the function itself barely runs.
    expect(res.headers["Cache-Control"]).toContain("s-maxage=600");
  });

  it("400s an unsupported country and names what it supports", () => {
    const res = mockRes();
    handler(mockReq({ country: "PA" }), res);
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toBe("unknown_country");
    expect(res.body.supported).toEqual(["SV"]);
  });

  it("503s when the catalog is missing instead of serving an empty payload", () => {
    // "No zones" and "the data did not deploy" look identical to a
    // channel, and only one of them is an incident.
    seam.setCatalog("SV", null);
    const res = mockRes();
    handler(mockReq(), res);
    expect(res.statusCode).toBe(503);
    expect(res.body).toEqual({ error: "data_unavailable" });
  });

  it("rejects non-GET with 405 and an Allow header", () => {
    const res = mockRes();
    handler(mockReq({}, { method: "POST" }), res);
    expect(res.statusCode).toBe(405);
    expect(res.headers.Allow).toBe("GET");
  });
});
