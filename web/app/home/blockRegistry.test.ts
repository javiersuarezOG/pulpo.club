// Unit tests for the Wave-4 home-page block registry. Pure-function
// table tests over the (user, flagEnabled) → blocks resolution.
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

const ALL_BLOCKS: readonly BlockId[] = [
  "hero", "featured", "usps",
  "shoreline", "top_10", "price_drops", "new_this_week",
];
const PAID_BLOCKS: readonly BlockId[] = [
  "shoreline", "top_10", "price_drops", "new_this_week",
];

describe("visibleBlocksFor — flag off (rollback path)", () => {
  // Pre-Wave-4 behavior: every tier sees every block, in author order.
  it.each([
    ["anonymous", anon],
    ["free",      free],
    ["pro",       pro],
    ["agency",    agency],
  ])("returns all blocks for %s", (_, user) => {
    expect(visibleBlocksFor(user as never, false)).toEqual(ALL_BLOCKS);
  });
});

describe("visibleBlocksFor — flag on (paid-home variant)", () => {
  it("anonymous sees all blocks", () => {
    expect(visibleBlocksFor(anon as never, true)).toEqual(ALL_BLOCKS);
  });

  it("free sees all blocks (filter is paid-only)", () => {
    expect(visibleBlocksFor(free as never, true)).toEqual(ALL_BLOCKS);
  });

  it("pro sees the trimmed paid-home list (no hero / featured / usps)", () => {
    expect(visibleBlocksFor(pro as never, true)).toEqual(PAID_BLOCKS);
  });

  it("agency sees the trimmed paid-home list", () => {
    expect(visibleBlocksFor(agency as never, true)).toEqual(PAID_BLOCKS);
  });
});

describe("HOME_BLOCKS — author-order + tier coverage invariants", () => {
  it("renders in the author order encoded in HOME_BLOCKS", () => {
    const authored = HOME_BLOCKS.map((b) => b.id);
    expect(visibleBlocksFor(anon as never, false)).toEqual(authored);
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
  it("treats undefined user as anonymous (flag on)", () => {
    expect(visibleBlocksFor(undefined as never, true)).toEqual(ALL_BLOCKS);
  });

  it("treats unknown plan as free (per gating.ts tierFor)", () => {
    expect(
      visibleBlocksFor({ plan: "mystery_tier" as never } as never, true),
    ).toEqual(ALL_BLOCKS);
  });
});
