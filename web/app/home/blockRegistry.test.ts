// Unit tests for the home-page block registry. Pure-function table
// tests over the (user, flags) → blocks resolution.
//
// The matrix is the spec. If a row goes red, downstream PostHog
// dashboards filtering on `paid_home_rendered.blocks_visible` will
// disagree with what production actually renders.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { visibleBlocksFor, type BlockId } from "./blockRegistry";

type User = { plan?: "free" | "pro" | "agency" } | null;

const anon: User = null;
const free: User = { plan: "free" };
const pro: User = { plan: "pro" };
const agency: User = { plan: "agency" };

const ALL_FLAGS_OFF = { paid_home_variant_v1: false, usp_popup_v1: false, hero_v4: false };
const PAID_HOME_ON  = { paid_home_variant_v1: true,  usp_popup_v1: false, hero_v4: false };
const POPUP_ON      = { paid_home_variant_v1: false, usp_popup_v1: true,  hero_v4: false };
const BOTH_ON       = { paid_home_variant_v1: true,  usp_popup_v1: true,  hero_v4: false };
const HERO_V4_ON    = { paid_home_variant_v1: false, usp_popup_v1: false, hero_v4: true  };
const ALL_FLAGS_ON  = { paid_home_variant_v1: true,  usp_popup_v1: true,  hero_v4: true  };

const ALL_BLOCKS: readonly BlockId[] = [
  "hero", "featured", "usps",
  "shoreline", "top_10", "price_drops", "new_this_week",
];
// Post-Wave-5 paid trim: hero stays (image-only — CTA gated in
// component), featured/usps/shoreline drop. Catalogue shelves stay.
const PAID_BLOCKS: readonly BlockId[] = [
  "hero", "top_10", "price_drops", "new_this_week",
];
const ALL_BLOCKS_NO_USPS: readonly BlockId[] = [
  "hero", "featured",
  "shoreline", "top_10", "price_drops", "new_this_week",
];

// localStorage stub — visibleBlocksFor reads window.localStorage for
// per-block dev overrides. Default to empty so tests aren't polluted
// by a real browser state.
beforeEach(() => {
  vi.stubGlobal("window", {
    localStorage: {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    },
  } as unknown as Window);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("visibleBlocksFor — all flags off (rollback path)", () => {
  // Legacy behavior: every tier sees every block, in author order.
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

  it("pro sees the trimmed paid-home list (hero image + shelves)", () => {
    expect(visibleBlocksFor(pro as never, PAID_HOME_ON)).toEqual(PAID_BLOCKS);
  });

  it("agency sees the trimmed paid-home list (hero image + shelves)", () => {
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

describe("visibleBlocksFor — hero_v4 flag", () => {
  // Wave 5#7+#9: the new white hero absorbs the featured-listing visually,
  // so the standalone `featured` block drops from the homepage flow.
  it.each([
    ["anonymous", anon],
    ["free",      free],
  ])("drops `featured` for %s, keeps the rest", (_, user) => {
    const out = visibleBlocksFor(user as never, HERO_V4_ON);
    expect(out).not.toContain("featured");
    expect(out).toContain("hero");
    expect(out).toContain("usps");
    expect(out).toContain("shoreline");
  });

  it.each([
    ["pro",       pro],
    ["agency",    agency],
  ])("for paid %s with paid_home off: drops `featured` only", (_, user) => {
    const out = visibleBlocksFor(user as never, HERO_V4_ON);
    expect(out).not.toContain("featured");
    // shoreline is visible when paid_home flag is off — the legacy
    // rollback path. The matrix VISIBILITY value for paid is false, but
    // it only applies when paid_home_variant_v1 is on.
    expect(out).toContain("shoreline");
  });

  it("composes with usp_popup_v1: both `featured` and `usps` gone", () => {
    const out = visibleBlocksFor(anon as never, {
      paid_home_variant_v1: false,
      usp_popup_v1:         true,
      hero_v4:              true,
    });
    expect(out).not.toContain("featured");
    expect(out).not.toContain("usps");
    expect(out).toContain("hero");
  });

  it("composes with all flags on for paid: only hero + shelves remain", () => {
    const out = visibleBlocksFor(pro as never, ALL_FLAGS_ON);
    expect(out).toEqual(["hero", "top_10", "price_drops", "new_this_week"]);
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

describe("visibleBlocksFor — per-block dev overrides", () => {
  it("force_show overrides a tier-hidden block", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (k: string) =>
          k === "pulpo-block-overrides" ? JSON.stringify({ shoreline: "force_show" }) : null,
        setItem: () => {},
        removeItem: () => {},
      },
    } as unknown as Window);
    // Pro user with paid_home on normally hides shoreline. Override wins.
    expect(visibleBlocksFor(pro as never, PAID_HOME_ON)).toContain("shoreline");
  });

  it("force_hide overrides a tier-visible block", () => {
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (k: string) =>
          k === "pulpo-block-overrides" ? JSON.stringify({ hero: "force_hide" }) : null,
        setItem: () => {},
        removeItem: () => {},
      },
    } as unknown as Window);
    expect(visibleBlocksFor(anon as never, ALL_FLAGS_OFF)).not.toContain("hero");
  });
});
