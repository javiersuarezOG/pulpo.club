// Anchors the exact-lookup search matcher. If this goes red the
// /browse search bar will either over-match (false positives) or
// under-match (lookups by id, broker URL, or zone fail).
//
// The matcher is "every token must be a substring of the haystack",
// where the haystack is a folded (lowercased + diacritic-stripped)
// concatenation of id / source_id / source_label / zone_name /
// province_state / title.en / title.es / original_url.

import { describe, it, expect } from "vitest";
import { tokenize, matchesQuery, matchesQueryString, scoreListing, buildSuggestions } from "./search-match";
import type { Listing } from "../data/types";

function L(overrides: Partial<Listing>): Listing {
  return {
    id: "remax__001461165132",
    title: { en: "Beachfront lot in El Tunco", es: "Lote frente al mar en El Tunco" },
    description: { en: "" },
    usps: [],
    url_language: "en",
    zone_name: "El Tunco",
    region: "La Libertad",
    country: "SV",
    province_state: "La Libertad, El Salvador",
    land_type: "residential",
    size_m2: 1000,
    price: 500_000,
    previous_price: null,
    price_per_m2: 500,
    zone: "el-tunco",
    zone_percentile: 0,
    price_vs_zone_median: 0,
    price_vs_zone_pct: 0,
    zone_price_per_m2_min: null,
    zone_price_per_m2_max: null,
    zone_comp_count: 0,
    zone_comparison_scope: "zone",
    photos: [],
    thumbnail_url: null,
    photos_count: 0,
    hero_photo_quality_score: null,
    has_text_overlay: null,
    hero_eligible: false,
    card_eligible: false,
    first_seen_date: 0,
    days_listed: 0,
    is_repriced: false,
    source_type: "on_market",
    source_label: "RE/MAX",
    source_id: "001461165132",
    beachfront_tier: "near_beach",
    has_ocean_view: false,
    has_mountain_view: false,
    has_water_body: false,
    is_flat: false,
    has_water: false,
    has_power: false,
    has_sewage: null,
    road_access_type: "unknown",
    readiness_score: 0,
    zoning_use: null,
    dist_beach_km: null,
    dist_airport_km: null,
    dist_nearest_town_km: null,
    has_lat_lng: true,
    geocoding_confidence: "high",
    geocoding_source: "extracted",
    geocoding_reference: null,
    existence_status: null,
    is_sold: false,
    original_url: "https://www.remax.com.sv/sv/property/lote-1404?referer=abc",
    rank: null,
    rank_score: null,
    value_score: null,
    location_score: null,
    momentum_score: null,
    property_type: "land",
    bedrooms: null,
    master_category: "beach",
    subcategory: "land",
    discovery_tags: [],
    star_rating: 0,
    is_incomplete: false,
    ...overrides,
  };
}

describe("tokenize", () => {
  it("returns empty for empty / whitespace / null", () => {
    expect(tokenize("")).toEqual([]);
    expect(tokenize("   ")).toEqual([]);
    expect(tokenize(null)).toEqual([]);
    expect(tokenize(undefined)).toEqual([]);
  });

  it("lowercases + strips accents + splits on whitespace", () => {
    expect(tokenize("Playa El Tunco")).toEqual(["playa", "el", "tunco"]);
    expect(tokenize("Conchaguá")).toEqual(["conchagua"]);
    expect(tokenize("  FOO   bar ")).toEqual(["foo", "bar"]);
  });
});

describe("matchesQuery", () => {
  it("empty token list matches every listing", () => {
    expect(matchesQuery(L({}), [])).toBe(true);
    expect(matchesQuery(L({}), tokenize(""))).toBe(true);
    expect(matchesQuery(L({}), tokenize("   "))).toBe(true);
  });

  it("matches by raw source_id (paste-from-card)", () => {
    expect(matchesQueryString(L({}), "001461165132")).toBe(true);
    // Bare numeric that's NOT anywhere in the haystack → no match.
    expect(matchesQueryString(L({}), "9999999999")).toBe(false);
  });

  it("matches by Pulpo composite id", () => {
    expect(matchesQueryString(L({}), "remax__001461165132")).toBe(true);
  });

  it("matches by broker URL fragment (slug + ?referer= intact)", () => {
    expect(matchesQueryString(L({}), "lote-1404")).toBe(true);
    expect(matchesQueryString(L({}), "remax.com.sv")).toBe(true);
    expect(matchesQueryString(L({}), "referer=abc")).toBe(true);
  });

  it("matches by zone (accent-folded)", () => {
    expect(matchesQueryString(L({}), "el tunco")).toBe(true);
    expect(matchesQueryString(L({}), "EL TUNCO")).toBe(true);
    expect(matchesQueryString(L({ zone_name: "Conchaguá" }), "conchagua")).toBe(true);
  });

  it("matches by title in either locale", () => {
    expect(matchesQueryString(L({}), "beachfront lot")).toBe(true);
    expect(matchesQueryString(L({}), "frente al mar")).toBe(true);
  });

  it("multi-token: every token must hit", () => {
    expect(matchesQueryString(L({}), "tunco lote-1404")).toBe(true);
    expect(matchesQueryString(L({}), "tunco mizata")).toBe(false);
  });

  it("matches by source_label (broker name)", () => {
    expect(matchesQueryString(L({}), "RE/MAX")).toBe(true);
    expect(matchesQueryString(L({}), "remax")).toBe(true);
  });

  it("null listing → no match for non-empty query, match for empty", () => {
    expect(matchesQuery(null, ["foo"])).toBe(false);
    expect(matchesQuery(null, [])).toBe(true);
    expect(matchesQuery(undefined, [])).toBe(true);
  });

  it("does not crash on partially-null fields", () => {
    const stripped = L({
      id: "goodlife__abc",
      title: { en: "" } as Listing["title"],
      original_url: null,
      source_label: "",
      source_id: "abc",
    });
    expect(matchesQueryString(stripped, "tunco")).toBe(true);
    // remax appears nowhere in this stripped fixture.
    expect(matchesQueryString(stripped, "remax")).toBe(false);
  });
});

describe("scoreListing", () => {
  it("returns 0 for empty tokens or null listing (non-query path untouched)", () => {
    expect(scoreListing(L({}), [])).toBe(0);
    expect(scoreListing(L({}), tokenize(""))).toBe(0);
    expect(scoreListing(null, ["tunco"])).toBe(0);
    expect(scoreListing(undefined, ["tunco"])).toBe(0);
  });

  it("title hit outranks a zone-only hit outranks an id/url-only hit", () => {
    // "playa" appears only in the title here.
    const titleHit = L({
      title: { en: "Playa lot", es: "Lote playa" },
      zone_name: "Mizata",
      province_state: "La Libertad",
      id: "x__1",
      source_id: "1",
      source_label: "X",
      original_url: "https://x.com/a",
    });
    // "playa" appears only in the zone label.
    const zoneHit = L({
      title: { en: "Lot", es: "Lote" },
      zone_name: "Playa El Zonte",
      province_state: "La Libertad",
      id: "x__2",
      source_id: "2",
      source_label: "X",
      original_url: "https://x.com/b",
    });
    // "playa" appears only in the URL slug.
    const urlHit = L({
      title: { en: "Lot", es: "Lote" },
      zone_name: "Mizata",
      province_state: "La Libertad",
      id: "x__3",
      source_id: "3",
      source_label: "X",
      original_url: "https://x.com/playa-lot",
    });
    const toks = tokenize("playa");
    expect(scoreListing(titleHit, toks)).toBeGreaterThan(scoreListing(zoneHit, toks));
    expect(scoreListing(zoneHit, toks)).toBeGreaterThan(scoreListing(urlHit, toks));
  });

  it("gives a word-boundary boost over a mid-substring hit", () => {
    const wholeWord = L({ title: { en: "tunco lot", es: "" }, zone_name: "z", province_state: "p", original_url: "" });
    const midWord = L({ title: { en: "xtuncox lot", es: "" }, zone_name: "z", province_state: "p", original_url: "" });
    const toks = tokenize("tunco");
    expect(scoreListing(wholeWord, toks)).toBeGreaterThan(scoreListing(midWord, toks));
  });

  it("is null-safe on stripped fields", () => {
    const stripped = L({ title: { en: "" } as Listing["title"], original_url: null, source_label: "" });
    expect(() => scoreListing(stripped, tokenize("tunco"))).not.toThrow();
    expect(scoreListing(stripped, tokenize("tunco"))).toBeGreaterThan(0);
  });
});

describe("buildSuggestions", () => {
  // A small mixed catalog: two El Tunco zones, one Mizata, mixed types.
  const catalog: Listing[] = [
    L({ id: "a__1", zone_name: "El Tunco", land_type: "residential", title: { en: "Tunco beach lot", es: "Lote playa Tunco" }, thumbnail_url: "https://x/a.jpg" }),
    L({ id: "a__2", zone_name: "El Tunco", land_type: "tourist", title: { en: "Tunco hotel plot", es: "Hotel Tunco" } }),
    L({ id: "a__3", zone_name: "El Tunco Norte", land_type: "residential", title: { en: "North Tunco parcel", es: "Parcela Tunco norte" } }),
    L({ id: "a__4", zone_name: "Mizata", land_type: "commercial", title: { en: "Mizata point", es: "Punta Mizata" } }),
  ];

  it("returns [] below the 2-char gate", () => {
    expect(buildSuggestions("t", catalog)).toEqual([]);
    expect(buildSuggestions("", catalog)).toEqual([]);
    expect(buildSuggestions(null, catalog)).toEqual([]);
    expect(buildSuggestions("tu", null)).toEqual([]);
  });

  it("dedups zones and ranks them by listing count", () => {
    const sugs = buildSuggestions("tunco", catalog, { max: 8 });
    const zones = sugs.filter((s) => s.kind === "zone");
    // "El Tunco" (2 listings) and "El Tunco Norte" (1) — deduped, El Tunco first.
    expect(zones.map((z) => z.value)).toEqual(["El Tunco", "El Tunco Norte"]);
    const elTunco = zones.find((z) => z.value === "El Tunco");
    expect(elTunco && "count" in elTunco && elTunco.count).toBe(2);
  });

  it("matches land types via the injected localized label", () => {
    const sugs = buildSuggestions("resid", catalog, {
      landTypeLabel: (k) => (k === "residential" ? "Residential" : k),
    });
    const lt = sugs.find((s) => s.kind === "land_type");
    expect(lt && lt.kind === "land_type" && lt.value).toBe("residential");
  });

  it("caps total at max and titles at 5", () => {
    const many = Array.from({ length: 20 }, (_, i) =>
      L({ id: `z__${i}`, zone_name: `Zone ${i}`, title: { en: `Tunco listing ${i}`, es: "" } }),
    );
    const sugs = buildSuggestions("tunco", many, { max: 8 });
    expect(sugs.length).toBeLessThanOrEqual(8);
    expect(sugs.filter((s) => s.kind === "title").length).toBeLessThanOrEqual(5);
  });

  it("title suggestions carry the locale-correct display + thumb", () => {
    const sugs = buildSuggestions("tunco", catalog, { locale: "es", max: 8 });
    const title = sugs.find((s) => s.kind === "title");
    expect(title && title.kind === "title" && title.value.startsWith("Lote playa")).toBe(true);
    // The first catalog entry carries a thumbnail.
    const withThumb = sugs.find((s) => s.kind === "title" && s.thumb);
    expect(withThumb).toBeTruthy();
  });
});
