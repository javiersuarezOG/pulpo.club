// Unit tests for the home-page block registry. Pure-function table
// tests over the (user, flags) → blocks resolution.
//
// The matrix is the spec. If a row goes red, downstream PostHog
// dashboards filtering on `paid_home_rendered.blocks_visible` will
// disagree with what production actually renders.

import { describe, expect, it } from "vitest";
import { visibleBlocksFor, HOME_BLOCKS, type BlockId } from "./blockRegistry";

type User = { plan?: "free" | "pro" | "agency" } | null;

const anon: User = null;
const free: User = { plan: "free" };
const pro: User = { plan: "pro" };
const agency: User = { plan: "agency" };

const ALL_FLAGS_OFF = { paid_home_variant_v1: false, usp_popup_v1: false };
const PAID_HOME_ON  = { paid_home_variant_v1: true,  usp_popup_v1: false };
const POPUP_ON      = { paid_home_variant_v1: false, usp_popup_v1: true  };
const BOTH_ON       = { paid_home_variant_v1: true,  usp_popup_v1: true  };

const ALL_BLOCKS: readonly BlockId[] = [
  "hero", "featured", "usps",
  "shoreline", "top_10", "price_drops", "new_this_week",
];
const PAID_BLOCKS: readonly BlockId[] = [
  "shoreline", "top_10", "price_drops", "new_this_week",
];
const ALL_BLOCKS_NO_USPS: readonly BlockId[] = [
  "hero", "featured",
  "shoreline", "top_10", "price_drops", "new_this_week",
];

describe("visibleBlocksFor — all flags off (rollback path)", () => {
  // Pre-Wave-4 behavior: every tier sees every block, in author order.
  it.each([
    ["anonymous", anon],
    ["free",      free],
    ["pro",       pro],
    ["agency",    agency],
  ])("returns all blocks for %s", (_, user) => {
    expect(visibleBlocksFor(user as never, ALL_FLAGS_OFF)).toEqual(ALL_BLOCKS);
  });
});

describe("visibleBlocksFor — paid_home_variant_v1 only", () => {
  it("anonymous sees all blocks", () => {
    expect(visibleBlocksFor(anon as never, PAID_HOME_ON)).toEqual(ALL_BLOCKS);
  });

  it("free sees all blocks (filter is paid-only)", () => {
    expect(visibleBlocksFor(free as never, PAID_HOME_ON)).toEqual(ALL_BLOCKS);
  });

  it("pro sees the trimmed paid-home list", () => {
    expect(visibleBlocksFor(pro as never, PAID_HOME_ON)).toEqual(PAID_BLOCKS);
  });

  it("agency sees the trimmed paid-home list", () => {
    expect(visibleBlocksFor(agency as never, PAID_HOME_ON)).toEqual(PAID_BLOCKS);
  });
});

describe("visibleBlocksFor — usp_popup_v1 only", () => {
  // The popup-migration flag drops `usps` for every tier (the popup
  // is mounted separately at the homepage root).
  it.each([
    ["anonymous", anon],
    ["free",      free],
    ["pro",       pro],
    ["agency",    agency],
  ])("drops `usps` for %s", (_, user) => {
    expect(visibleBlocksFor(user as never, POPUP_ON)).toEqual(ALL_BLOCKS_NO_USPS);
  });
});

describe("visibleBlocksFor — both flags on (compose)", () => {
  it("anonymous: usps gone, hero + featured still visible", () => {
    expect(visibleBlocksFor(anon as never, BOTH_ON)).toEqual(ALL_BLOCKS_NO_USPS);
  });

  it("free: usps gone, hero + featured still visible", () => {
    expect(visibleBlocksFor(free as never, BOTH_ON)).toEqual(ALL_BLOCKS_NO_USPS);
  });

  it("pro: usps already filtered by paid_home; popup flag is redundant", () => {
    // PAID_BLOCKS already excludes usps; popup flag is a no-op for pro.
    expect(visibleBlocksFor(pro as never, BOTH_ON)).toEqual(PAID_BLOCKS);
  });
});

describe("HOME_BLOCKS — author-order + tier coverage invariants", () => {
  it("renders in the author order encoded in HOME_BLOCKS (all flags off)", () => {
    const authored = HOME_BLOCKS.map((b) => b.id);
    expect(visibleBlocksFor(anon as never, ALL_FLAGS_OFF)).toEqual(authored);
  });

  it("every block lists at least one tier — no orphan entries", () => {
    for (const block of HOME_BLOCKS) {
      expect(block.visibleFor.length).toBeGreaterThan(0);
    }
  });

  it("the carousel blocks are visible for every tier (no accidental gate)", () => {
    const carousels: BlockId[] = ["shoreline", "top_10", "price_drops", "new_this_week"];
    for (const id of carousels) {
      const entry = HOME_BLOCKS.find((b) => b.id === id);
      expect(entry).toBeDefined();
      expect(entry!.visibleFor).toEqual(
        expect.arrayContaining(["anonymous", "free", "pro", "agency"]),
      );
    }
  });
});

describe("visibleBlocksFor — defensive defaults", () => {
  it("treats undefined user as anonymous (paid_home flag on)", () => {
    expect(visibleBlocksFor(undefined as never, PAID_HOME_ON)).toEqual(ALL_BLOCKS);
  });

  it("treats unknown plan as free (per gating.ts tierFor)", () => {
    expect(
      visibleBlocksFor({ plan: "mystery_tier" as never } as never, PAID_HOME_ON),
    ).toEqual(ALL_BLOCKS);
  });
});
