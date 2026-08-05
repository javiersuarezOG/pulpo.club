// Similarity selection for the detail-page "Similar listings" shelf.
// Pure function, so we assert the ranking + filtering contract directly.

import { describe, expect, it } from "vitest";
import { scoreSimilarity, similarListings } from "./similar-listings";
import type { Listing } from "../data/types";

// Minimal Listing factory — only the fields the similarity logic reads.
function L(over: Partial<Listing>): Listing {
  return {
    id: "x",
    master_category: "beach",
    subcategory: "land",
    land_type: "residential",
    zone_name: "El Tunco",
    price: 100_000,
    is_incomplete: false,
    is_sold: false,
    rank: 100,
    ...over,
  } as Listing;
}

describe("scoreSimilarity", () => {
  it("rewards same category, kind, zone, and close price", () => {
    const ref = L({ id: "ref" });
    const twin = L({ id: "twin", price: 105_000 });
    const distant = L({ id: "d", master_category: "lake", subcategory: "condos", land_type: "commercial", zone_name: "Coatepeque", price: 500_000 });
    expect(scoreSimilarity(ref, twin)).toBeGreaterThan(scoreSimilarity(ref, distant));
  });

  it("gives near-zero price credit past the 60% band", () => {
    const ref = L({ id: "ref", price: 100_000 });
    const near = L({ id: "n", price: 110_000 });
    const far = L({ id: "f", price: 200_000 });
    // Both share cat/kind/zone; the only differentiator is price proximity.
    expect(scoreSimilarity(ref, near)).toBeGreaterThan(scoreSimilarity(ref, far));
  });
});

describe("similarListings", () => {
  const ref = L({ id: "ref", zone_name: "El Tunco", price: 100_000 });

  it("excludes the reference, incomplete, and sold listings", () => {
    const all = [
      ref,
      L({ id: "self-dupe", ...ref }),           // same id as ref → excluded
      L({ id: "incomplete", is_incomplete: true }),
      L({ id: "sold", is_sold: true }),
      L({ id: "good", price: 102_000 }),
    ];
    const out = similarListings(ref, all, 4).map((l) => l.id);
    expect(out).toContain("good");
    expect(out).not.toContain("ref");
    expect(out).not.toContain("self-dupe");
    expect(out).not.toContain("incomplete");
    expect(out).not.toContain("sold");
  });

  it("requires shared category OR zone — never pads with unrelated", () => {
    const all = [
      ref,
      L({ id: "unrelated", master_category: "lake", zone_name: "Coatepeque", land_type: "commercial" }),
    ];
    expect(similarListings(ref, all, 4)).toHaveLength(0);
  });

  it("caps at the requested limit, best-first", () => {
    const all = [ref];
    for (let i = 0; i < 10; i++) {
      all.push(L({ id: `c${i}`, price: 100_000 + i * 1_000, rank: 50 + i }));
    }
    const out = similarListings(ref, all, 4);
    expect(out).toHaveLength(4);
    // Closest price + best rank should lead.
    expect(out[0].id).toBe("c0");
  });

  it("breaks ties toward the better-ranked listing", () => {
    const all = [
      ref,
      L({ id: "worse", price: 100_000, rank: 800 }),
      L({ id: "better", price: 100_000, rank: 3 }),
    ];
    const out = similarListings(ref, all, 2).map((l) => l.id);
    expect(out[0]).toBe("better");
  });

  it("still matches on zone when category differs", () => {
    const ref2 = L({ id: "ref2", master_category: null, zone_name: "El Tunco" });
    const all = [ref2, L({ id: "same-zone", master_category: null, zone_name: "El Tunco" })];
    expect(similarListings(ref2, all, 4).map((l) => l.id)).toContain("same-zone");
  });
});
