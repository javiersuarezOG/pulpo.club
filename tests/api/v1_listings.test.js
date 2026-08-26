// GET /api/v1/listings + /api/v1/listings/:id
//
// The parity block at the bottom is the one that matters most: it
// asserts the endpoint returns exactly what the website's own engine
// would, for the same query. If those ever diverge, something stopped
// going through shared/ — which is the single failure mode this whole
// API layer exists to prevent.
//
// All fixtures synthetic; these specs never read web/data.

import { afterEach, describe, expect, it } from "vitest";
import handler from "../../api/v1/listings.ts";
import detailHandler from "../../api/v1/listings/[id].ts";
import { __testing__ } from "../../api/v1/_catalog.ts";
import { selectListings, adaptAll } from "../../api/v1/_serve.ts";
import {
  applyFilters,
  applyRankCap,
  makeDefaultFilters,
} from "../../shared/engine/filters.ts";
import { readFilterFromURL } from "../../shared/engine/params.ts";

function mockRes() {
  return {
    statusCode: 200, headers: {}, body: null,
    setHeader(k, v) { this.headers[k] = v; return this; },
    status(c) { this.statusCode = c; return this; },
    json(p) { this.body = p; return this; },
  };
}

let ip = 0;
function mockReq(url = "/api/v1/listings", query = {}) {
  return {
    method: "GET",
    url,
    query,
    // Fresh IP per request: the limiter is module-level and shared
    // across every test in this file.
    headers: { "x-forwarded-for": `198.18.${Math.floor(ip / 250) % 250}.${(ip++ % 250) + 1}` },
  };
}

// Raw pipeline rows (pre-adapter), the shape ranked.list.json holds.
const row = (over = {}) => ({
  source: "remax",
  source_id: String(Math.random()).slice(2, 10),
  zone: "el-tunco",
  country: "SV",
  department: "La Libertad",
  title_canonical: { en: "Ocean-view lot", es: "Terreno con vista al mar" },
  short_description_canonical: { en: "A lot.", es: "Un terreno." },
  reasons_to_buy: [],
  price_usd: 100_000,
  area_m2: 1000,
  price_per_m2: 100,
  property_type: "land",
  subcategory: "land",
  master_category: "beach",
  discovery_tags: ["top_rated"],
  photo_urls: ["https://cdn.example.com/a.jpg"],
  hero_photo_path: "/photos/remax_a.jpg",
  photos_count: 1,
  rank_score: 50,
  first_seen_at: new Date().toISOString(),
  is_sold: false,
  is_incomplete: false,
  ...over,
});

const setCatalog = (rows, generatedAt = "2026-08-21T04:04:32Z") =>
  __testing__.setCatalog("SV", { rows, generatedAt, country: "SV" });

afterEach(() => __testing__.reset());

describe("GET /api/v1/listings", () => {
  it("returns an envelope with the catalog timestamp, not request time", () => {
    setCatalog([row(), row()]);
    const res = mockRes();
    handler(mockReq(), res);

    expect(res.statusCode).toBe(200);
    expect(res.body.version).toBe("v1");
    expect(res.body.country).toBe("SV");
    expect(res.body.generated_at).toBe("2026-08-21T04:04:32Z");
    expect(res.body.total).toBe(2);
    expect(res.body.data).toHaveLength(2);
  });

  it("mints the canonical id and an absolute deep link", () => {
    setCatalog([row({ source: "remax", source_id: "12345" })]);
    const res = mockRes();
    handler(mockReq(), res);

    const l = res.body.data[0];
    // This id format is already in live Instagram and newsletter URLs.
    expect(l.id).toBe("remax__12345");
    expect(l.url).toBe("https://pulpo.club/listing/remax__12345");
  });

  it("makes photo URLs absolute so a chat client can fetch them", () => {
    setCatalog([row({ hero_photo_path: "/photos/remax_a.jpg", photo_urls: [] })]);
    const res = mockRes();
    handler(mockReq(), res);

    const photos = res.body.data[0].photos;
    for (const p of photos) {
      const url = typeof p === "string" ? p : p.url;
      if (url) expect(url).toMatch(/^https?:\/\//);
    }
  });

  it("keeps bilingual fields as {en,es} — no locale param, one cache entry", () => {
    setCatalog([row()]);
    const res = mockRes();
    handler(mockReq(), res);

    const l = res.body.data[0];
    expect(l.title.en).toBe("Ocean-view lot");
    expect(l.title.es).toBe("Terreno con vista al mar");
  });

  it("hides sold and incomplete listings, matching every other surface", () => {
    setCatalog([
      row({ source_id: "ok" }),
      row({ source_id: "sold", is_sold: true }),
      row({ source_id: "partial", is_incomplete: true }),
    ]);
    const res = mockRes();
    handler(mockReq(), res);

    expect(res.body.total).toBe(1);
    expect(res.body.data[0].id).toBe("remax__ok");
  });

  it("paginates with limit/offset and reports the FILTERED total", () => {
    setCatalog(Array.from({ length: 25 }, (_, i) =>
      row({ source_id: `l${i}`, rank_score: 100 - i })));

    const res = mockRes();
    handler(mockReq("/api/v1/listings?limit=5&offset=10"), res);

    // total is the whole matching set, so a channel can decide whether
    // to offer "more results".
    expect(res.body.total).toBe(25);
    expect(res.body.data).toHaveLength(5);
    expect(res.body.offset).toBe(10);
    expect(res.body.data[0].id).toBe("remax__l10");
  });

  it("caps limit at 50 and ignores junk instead of erroring", () => {
    setCatalog(Array.from({ length: 60 }, (_, i) => row({ source_id: `l${i}` })));

    const capped = mockRes();
    handler(mockReq("/api/v1/listings?limit=999"), capped);
    expect(capped.body.data).toHaveLength(50);

    // A bot sending limit=abc should get the default page, not a 400 it
    // cannot explain to a user.
    const junk = mockRes();
    handler(mockReq("/api/v1/listings?limit=abc"), junk);
    expect(junk.statusCode).toBe(200);
    expect(junk.body.data).toHaveLength(10);
  });

  it("supports every documented sort", () => {
    setCatalog([
      row({ source_id: "cheap", price_usd: 10_000, rank_score: 10 }),
      row({ source_id: "dear", price_usd: 900_000, rank_score: 90 }),
    ]);

    const first = (qs) => {
      const res = mockRes();
      handler(mockReq(`/api/v1/listings?${qs}`), res);
      return res.body.data[0].id;
    };

    expect(first("sort=rank")).toBe("remax__dear");
    expect(first("sort=price_asc")).toBe("remax__cheap");
    expect(first("sort=price_desc")).toBe("remax__dear");
    // Unknown sort falls back to rank rather than 400ing.
    expect(first("sort=banana")).toBe("remax__dear");
  });

  it("sets a CDN cache header so origin cost stays near zero", () => {
    setCatalog([row()]);
    const res = mockRes();
    handler(mockReq(), res);
    expect(res.headers["Cache-Control"]).toContain("s-maxage=300");
  });

  it("400s an unknown country and 503s a missing catalog", () => {
    const bad = mockRes();
    handler(mockReq("/api/v1/listings", { country: "PA" }), bad);
    expect(bad.statusCode).toBe(400);
    expect(bad.body.error).toBe("unknown_country");

    __testing__.setCatalog("SV", null);
    const gone = mockRes();
    handler(mockReq(), gone);
    expect(gone.statusCode).toBe(503);
    expect(gone.body).toEqual({ error: "data_unavailable" });
  });

  it("rejects non-GET with 405 + Allow", () => {
    const res = mockRes();
    const req = mockReq();
    req.method = "POST";
    handler(req, res);
    expect(res.statusCode).toBe(405);
    expect(res.headers.Allow).toBe("GET");
  });
});

describe("GET /api/v1/listings/:id", () => {
  it("returns one listing by canonical id", () => {
    setCatalog([row({ source_id: "12345" }), row({ source_id: "other" })]);
    const res = mockRes();
    detailHandler(mockReq("/api/v1/listings/remax__12345", { id: "remax__12345" }), res);

    expect(res.statusCode).toBe(200);
    expect(res.body.data.id).toBe("remax__12345");
    expect(res.body.generated_at).toBe("2026-08-21T04:04:32Z");
  });

  it("400s a malformed or traversal-shaped id before touching the catalog", () => {
    setCatalog([row()]);
    for (const id of ["", "remax", "remax__../../etc/passwd", "remax|123"]) {
      const res = mockRes();
      detailHandler(mockReq("/api/v1/listings/x", { id }), res);
      expect(res.statusCode, id).toBe(400);
      expect(res.body.error).toBe("invalid_param");
    }
  });

  it("404s unknown, sold and incomplete alike — no probing which ids we hold", () => {
    setCatalog([
      row({ source_id: "sold", is_sold: true }),
      row({ source_id: "partial", is_incomplete: true }),
    ]);
    for (const id of ["remax__nope", "remax__sold", "remax__partial"]) {
      const res = mockRes();
      detailHandler(mockReq("/api/v1/listings/x", { id }), res);
      expect(res.statusCode, id).toBe(404);
      expect(res.body).toEqual({ error: "not_found" });
    }
  });
});

describe("parity — the API and the website cannot diverge", () => {
  // The website runs applyFilters/applyRankCap over adapted listings on
  // every keystroke. The endpoint runs the same functions from the same
  // modules. These assertions fail the moment one side grows its own
  // copy of the logic, which is the exact drift the PRD is about.

  const rows = [
    row({ source_id: "a", subcategory: "land", price_usd: 50_000, rank_score: 80, master_category: "beach" }),
    row({ source_id: "b", subcategory: "land", price_usd: 300_000, rank_score: 90, master_category: "beach" }),
    row({ source_id: "c", subcategory: "homes", price_usd: 50_000, rank_score: 70, master_category: "beach" }),
    row({ source_id: "d", subcategory: "land", price_usd: 50_000, rank_score: 60, master_category: "lake" }),
    row({ source_id: "e", subcategory: "land", price_usd: 50_000, rank_score: 95, is_sold: true }),
  ];

  const queries = [
    "",
    "sub=land",
    "sub=land&pmax=250000",
    "master=beach&sub=land",
    "tag=top_rated",
    "pmin=60000",
    "rmax=1",
    "q=tunco",
  ];

  for (const qs of queries) {
    it(`"${qs || "(no filters)"}" returns the same ids the website engine would`, () => {
      const adapted = adaptAll(rows, "SV");

      // What /browse would show for this query.
      const websiteFilters = readFilterFromURL(qs, makeDefaultFilters());
      const website = applyRankCap(
        applyFilters(adapted, websiteFilters),
        websiteFilters.rank_max,
      ).map((l) => l.id).sort();

      // What the endpoint returns.
      const api = selectListings(adapted, `${qs}&limit=50`).listings.map((l) => l.id).sort();

      expect(api).toEqual(website);
    });
  }

  it("shares the sold-listing gate with the website", () => {
    const adapted = adaptAll(rows, "SV");
    expect(selectListings(adapted, "limit=50").listings.some((l) => l.is_sold)).toBe(false);
  });
});
