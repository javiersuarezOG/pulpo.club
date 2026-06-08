// Anchors the exact-lookup search matcher. If this goes red the
// /browse search bar will either over-match (false positives) or
// under-match (lookups by id, broker URL, or zone fail).
//
// The matcher is "every token must be a substring of the haystack",
// where the haystack is a folded (lowercased + diacritic-stripped)
// concatenation of id / source_id / source_label / zone_name /
// province_state / title.en / title.es / original_url.

import { describe, it, expect } from "vitest";
import { tokenize, matchesQuery, matchesQueryString } from "./search-match";
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
