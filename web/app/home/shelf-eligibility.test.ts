// Homepage hard-rule eligibility (P4). A listing only appears on a
// homepage shelf when it has a suitable LOCAL thumbnail: thumbnail_url
// present AND card_eligible === true (P5 forces card_eligible False for
// logos/placeholders). photos.length is no longer the gate.
//
// Display-gate contract (plan 003): inventory surfaces (Browse/Discover,
// Saved, map cards) keep the listing findable but swap a non-eligible
// IMAGE for the category fallback (see web/app/lib/card-image.ts) — they
// are not "exempt" from the image rule, only from the drop-the-listing
// rule. This spec exercises only the curated-shelf DROP behavior.

import { describe, it, expect } from "vitest";
import { pickTopRanked } from "./HomeShelf.jsx";

function L(over: Record<string, unknown>) {
  return {
    is_incomplete: false,
    thumbnail_url: "/photos/x.jpg",
    card_eligible: true,
    rank_score: 1,
    photos: ["https://b/1.jpg"],
    ...over,
  };
}

describe("homepage shelf eligibility (P4 hard rule)", () => {
  it("includes a listing with a local thumbnail + card_eligible", () => {
    const out = pickTopRanked([L({ rank_score: 5 })], 10);
    expect(out).toHaveLength(1);
  });

  it("excludes a listing with no local thumbnail (thumbnail_url null)", () => {
    // Has broker photos but no local derivative — the 404/broken-hero case.
    const out = pickTopRanked(
      [L({ thumbnail_url: null, photos: ["https://b/1.jpg", "https://b/2.jpg"] })],
      10,
    );
    expect(out).toHaveLength(0);
  });

  it("excludes a listing whose source is card-ineligible (logo/too-small)", () => {
    const out = pickTopRanked([L({ card_eligible: false })], 10);
    expect(out).toHaveLength(0);
  });

  it("excludes incomplete listings even with a good photo", () => {
    const out = pickTopRanked([L({ is_incomplete: true })], 10);
    expect(out).toHaveLength(0);
  });

  it("no longer admits a listing on photos.length alone", () => {
    // photos present, but no local thumbnail and not card_eligible.
    const out = pickTopRanked(
      [L({ thumbnail_url: null, card_eligible: false, photos: ["https://b/1.jpg"] })],
      10,
    );
    expect(out).toHaveLength(0);
  });

  it("ranks eligible listings by rank_score desc and caps at n", () => {
    const out = pickTopRanked(
      [L({ rank_score: 1 }), L({ rank_score: 9 }), L({ rank_score: 5 })],
      2,
    );
    expect(out).toHaveLength(2);
    expect(out[0].rank_score).toBe(9);
    expect(out[1].rank_score).toBe(5);
  });
});
