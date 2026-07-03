// listings-adapter.test.ts — PR-5 (WS4).
//
// adaptListing() must expose the raw lat/lng coordinates (for the map
// view) and clamp non-numbers to null so map read-sites can guard with
// hasCoords(). The ~0.5% of listings without coordinates must surface
// as null, not 0 or NaN.

import { describe, it, expect } from "vitest";
import { adaptListing } from "./listings";

describe("adaptListing — lat/lng passthrough (PR-5)", () => {
  it("passes numeric lat/lng through unchanged", () => {
    const out = adaptListing({ id: "x__1", lat: 13.495, lng: -89.383 });
    expect(out.lat).toBe(13.495);
    expect(out.lng).toBe(-89.383);
    expect(out.has_lat_lng).toBe(true);
  });

  it("clamps missing / non-numeric coordinates to null", () => {
    const missing = adaptListing({ id: "x__2" });
    expect(missing.lat).toBeNull();
    expect(missing.lng).toBeNull();
    expect(missing.has_lat_lng).toBe(false);

    const garbage = adaptListing({ id: "x__3", lat: "13.5", lng: null });
    expect(garbage.lat).toBeNull();
    expect(garbage.lng).toBeNull();
    expect(garbage.has_lat_lng).toBe(false);
  });

  it("clamps a half-populated coordinate pair to has_lat_lng=false", () => {
    // lat present but lng missing — not mappable.
    const out = adaptListing({ id: "x__4", lat: 13.5 });
    expect(out.lat).toBe(13.5);
    expect(out.lng).toBeNull();
    expect(out.has_lat_lng).toBe(false);
  });
});
