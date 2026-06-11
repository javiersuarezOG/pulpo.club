// Unit contract for the Free top-3 view exemption.
//
// `freeViewableIds` is the single source of truth shared by the home hero
// (HeroV5 FreeTopCard) and the open-gate (app.jsx openListing). If these
// drift, a Free viewer could see an unlocked card they can't open, or open
// a listing the hero never advertised. These tests pin the selection rule.

import { describe, it, expect } from "vitest";
import { pickTopRanked, freeViewableIds, FREE_VIEWABLE_COUNT } from "./free-view";

function mk(id: string, rank: number | null, opts: Partial<{ thumb: boolean; eligible: boolean }> = {}) {
  return {
    id,
    rank_score: rank,
    thumbnail_url: opts.thumb === false ? null : `/photos/${id}.jpg`,
    card_eligible: opts.eligible === false ? false : true,
  } as any;
}

describe("freeViewableIds", () => {
  it("selects exactly the top FREE_VIEWABLE_COUNT by rank_score", () => {
    const listings = [
      mk("a", 50), mk("b", 90), mk("c", 70), mk("d", 80), mk("e", 60),
    ];
    const ids = freeViewableIds(listings);
    expect(ids.size).toBe(FREE_VIEWABLE_COUNT);
    expect([...ids].sort()).toEqual(["b", "c", "d"].sort()); // 90, 80, 70
  });

  it("matches the hero's pickTop(…,3) — same set, no drift", () => {
    const listings = [
      mk("a", 50), mk("b", 90), mk("c", 70), mk("d", 80), mk("e", 60),
    ];
    const heroTop3 = new Set(pickTopRanked(listings, 3).map((l) => l.id));
    expect(freeViewableIds(listings)).toEqual(heroTop3);
  });

  it("excludes listings that are not card-eligible or have no thumbnail", () => {
    const listings = [
      mk("a", 99, { eligible: false }), // highest rank but not card-eligible
      mk("b", 95, { thumb: false }),    // no local thumbnail
      mk("c", 70), mk("d", 80), mk("e", 60),
    ];
    const ids = freeViewableIds(listings);
    expect(ids.has("a")).toBe(false);
    expect(ids.has("b")).toBe(false);
    expect([...ids].sort()).toEqual(["c", "d", "e"].sort());
  });

  it("ignores listings with null rank_score", () => {
    const listings = [mk("a", null), mk("b", 10), mk("c", 20)];
    expect([...freeViewableIds(listings)].sort()).toEqual(["b", "c"].sort());
  });

  it("is null/empty-safe", () => {
    expect(freeViewableIds(null).size).toBe(0);
    expect(freeViewableIds(undefined).size).toBe(0);
    expect(freeViewableIds([]).size).toBe(0);
  });
});
