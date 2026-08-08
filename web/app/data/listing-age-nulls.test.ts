// listing-age-nulls.test.ts
//
// `first_seen_date` is nullable, and null must never be treated as 0.
//
// Why this exists: `daysSince()` used to `return 0` for a missing or
// unparseable `first_seen_at`, which made an unknown-age listing
// indistinguishable from one first seen today. That's the same
// null-vs-zero conflation the `days_listed` mapper right below it
// explicitly warns against ("`null` means we couldn't extract it —
// DON'T conflate with 0"), one field over.
//
// The trap is that JS coerces null to 0 in a numeric comparison, so
// every bare `first_seen_date <= 7` silently passed unknown-age
// listings: they got the "New" badge, landed in the "new this week"
// shelf, survived the `status=new` browse facet, and sorted as the
// freshest items. Nothing threw; the UI just quietly lied.
//
// Each test below pins one of those surfaces. If someone "simplifies"
// a guard back to a bare comparison, exactly one of these fails and
// names the surface.

import { describe, it, expect } from "vitest";
import { adaptListing } from "./listings";
import { signalForListing } from "../components.jsx";
import { SHELVES } from "../config/shelves";
import type { Listing } from "./types";

describe("adaptListing — first_seen_date is null, not 0, when unknown", () => {
  it("maps a missing first_seen_at to null", () => {
    const out = adaptListing({ id: "s__1", source: "s", source_id: "1" });
    expect(out.first_seen_date).toBeNull();
  });

  it("maps an unparseable first_seen_at to null", () => {
    const out = adaptListing({
      id: "s__2", source: "s", source_id: "2",
      first_seen_at: "not-a-timestamp",
    });
    expect(out.first_seen_date).toBeNull();
  });

  it("still maps a real timestamp to a day count", () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 86_400_000).toISOString();
    const out = adaptListing({
      id: "s__3", source: "s", source_id: "3",
      first_seen_at: threeDaysAgo,
    });
    expect(out.first_seen_date).toBe(3);
  });

  it("keeps 0 meaningful — first seen today is 0, not null", () => {
    const out = adaptListing({
      id: "s__4", source: "s", source_id: "4",
      first_seen_at: new Date().toISOString(),
    });
    expect(out.first_seen_date).toBe(0);
  });
});

// Minimal shape for the pure predicates under test.
const li = (over: Partial<Listing>) => ({
  days_listed: null,
  first_seen_date: null,
  is_repriced: false,
  existence_status: "confirmed_current",
  ...over,
}) as unknown as Listing;

describe("signalForListing — unknown age renders no badge", () => {
  it("returns null when both age fields are null", () => {
    expect(signalForListing(li({}))).toBeNull();
  });

  it("fires New on a real first_seen_date fallback", () => {
    expect(signalForListing(li({ first_seen_date: 3 }))?.kind).toBe("new");
  });

  it("fires New when the listing was first seen today (0, not null)", () => {
    expect(signalForListing(li({ first_seen_date: 0 }))?.kind).toBe("new");
  });

  it("does not fire New on an old listing", () => {
    expect(signalForListing(li({ first_seen_date: 60 }))).toBeNull();
  });

  it("prefers days_listed over the first_seen_date fallback", () => {
    // Scraper parsed a real 200-day-old posting; Pulpo only scraped it
    // yesterday. The broker's date wins — no "New".
    expect(signalForListing(li({ days_listed: 200, first_seen_date: 1 }))).toBeNull();
  });
});

describe("SHELVES new_this_week — unknown age is excluded", () => {
  const shelf = SHELVES.find((s) => s.key === "new_this_week")!;

  it("excludes a null first_seen_date", () => {
    expect(shelf.filter(li({}))).toBe(false);
  });

  it("includes a genuinely fresh listing", () => {
    expect(shelf.filter(li({ first_seen_date: 2 }))).toBe(true);
  });

  it("includes a listing first seen today", () => {
    expect(shelf.filter(li({ first_seen_date: 0 }))).toBe(true);
  });

  it("excludes a listing older than the window", () => {
    expect(shelf.filter(li({ first_seen_date: 8 }))).toBe(false);
  });
});
