// Anchors the location-precision tier derivation. If this goes red the
// detail-page location note will misrepresent how the listing was
// geocoded. The four enum values + null are all the pipeline can emit;
// the test pins each one to a stable tier.

import { describe, it, expect } from "vitest";
import { deriveLocationPrecision } from "./location-precision";

describe("deriveLocationPrecision", () => {
  it("extracted source → precise", () => {
    expect(
      deriveLocationPrecision({
        geocoding_source: "extracted",
        geocoding_confidence: "high",
        has_lat_lng: true,
      }),
    ).toBe("precise");
  });

  it("estimated source → approximate (regardless of confidence)", () => {
    for (const conf of ["high", "medium", "low", null] as const) {
      expect(
        deriveLocationPrecision({
          geocoding_source: "estimated",
          geocoding_confidence: conf,
          has_lat_lng: true,
        }),
      ).toBe("approximate");
    }
  });

  it("nominatim source → approximate", () => {
    expect(
      deriveLocationPrecision({
        geocoding_source: "nominatim",
        geocoding_confidence: "high",
        has_lat_lng: true,
      }),
    ).toBe("approximate");
  });

  it("null source → unknown (don't claim precision we don't have)", () => {
    expect(
      deriveLocationPrecision({
        geocoding_source: null,
        geocoding_confidence: null,
        has_lat_lng: false,
      }),
    ).toBe("unknown");
  });

  it("null listing → unknown (don't crash on missing data)", () => {
    expect(deriveLocationPrecision(null)).toBe("unknown");
    expect(deriveLocationPrecision(undefined)).toBe("unknown");
  });
});
