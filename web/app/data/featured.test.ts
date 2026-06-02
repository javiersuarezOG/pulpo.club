// Unit tests for web/app/data/featured.ts — PRD P1-1 freshness path.
//
// `loadFeaturedJson` must treat expired payloads as unavailable so a
// rollback to the legacy hero block (which reads /data/featured.json
// directly when feature flags allow) cannot serve the 2026-05-08 pick
// to users.

import { describe, it, expect } from "vitest";
import { adaptFeaturedJson, isFeaturedExpired } from "./featured";

describe("isFeaturedExpired", () => {
  it("treats null as expired so callers fall through to legacy", () => {
    expect(isFeaturedExpired(null)).toBe(true);
  });

  it("treats missing expires_at as expired (defensive)", () => {
    expect(
      isFeaturedExpired(adaptFeaturedJson({ picked_at: "2026-06-03T00:00:00Z" })),
    ).toBe(true);
  });

  it("returns true when expires_at is in the past", () => {
    const adapted = adaptFeaturedJson({
      picked_at: "2026-05-07T00:00:00Z",
      expires_at: "2026-05-08T00:00:00Z",
    });
    const now = new Date("2026-06-03T00:00:00Z");
    expect(isFeaturedExpired(adapted, now)).toBe(true);
  });

  it("returns false when expires_at is in the future", () => {
    const adapted = adaptFeaturedJson({
      picked_at: "2026-06-03T00:00:00Z",
      expires_at: "2026-06-04T00:00:00Z",
    });
    const now = new Date("2026-06-03T01:00:00Z");
    expect(isFeaturedExpired(adapted, now)).toBe(false);
  });

  it("treats unparseable expires_at as expired", () => {
    const adapted = adaptFeaturedJson({
      picked_at: "2026-06-03T00:00:00Z",
      expires_at: "not-a-date",
    });
    expect(isFeaturedExpired(adapted)).toBe(true);
  });
});
