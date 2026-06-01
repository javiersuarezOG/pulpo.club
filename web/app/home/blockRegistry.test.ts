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

const ALL_FLAGS_OFF = { paid_home_variant_v1: false, usp_popup_v1: false, hero_v4: false, hero_v5: false };
const PAID_HOME_ON  = { paid_home_variant_v1: true,  usp_popup_v1: false, hero_v4: false, hero_v5: false };
const POPUP_ON      = { paid_home_variant_v1: false, usp_popup_v1: true,  hero_v4: false, hero_v5: false };
const BOTH_ON       = { paid_home_variant_v1: true,  usp_popup_v1: true,  hero_v4: false, hero_v5: false };
const HERO_V4_ON    = { paid_home_variant_v1: false, usp_popup_v1: false, hero_v4: true,  hero_v5: false };
const HERO_V5_ON    = { paid_home_variant_v1: false, usp_popup_v1: false, hero_v4: false, hero_v5: true  };
const ALL_FLAGS_ON  = { paid_home_variant_v1: true,  usp_popup_v1: true,  hero_v4: true,  hero_v5: false };

// Phase 3 — the catalogue shelves are now six (Beach × Land/Condos/
// Homes, then Lake × Land/Condos/Homes) instead of the legacy three
// (top_10, price_drops, new_this_week).
const SIX_TOP_SHELVES: readonly BlockId[] = [
  "top_beach_terrenos", "top_beach_condos", "top_beach_homes",
  "top_lake_terrenos",  "top_lake_condos",  "top_lake_homes",
];
// Wave-6: the legacy `usps` block was eliminated entirely. Tests
// below no longer reference it.
const ALL_BLOCKS: readonly BlockId[] = [
  "hero", "featured",
  "shoreline", ...SIX_TOP_SHELVES,
];
// Post-Wave-5 paid trim: hero stays (image-only — CTA gated in
// component), featured + shoreline drop. Catalogue shelves stay.
const PAID_BLOCKS: readonly BlockId[] = [
  "hero", ...SIX_TOP_SHELVES,
];
// Wave-6 hero_v5: replaces both `hero` and `shoreline` slots with the
// new editorial postcard-preview hero. `featured` stays.
const HERO_V5_BLOCKS: readonly BlockId[] = [
  "hero_v5", "featured",
  ...SIX_TOP_SHELVES,
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

describe("visibleBlocksFor — paid_home_variant_v1 only (production default)", () => {
  it("anonymous sees all blocks", () => {
    expect(visibleBlocksFor(anon as never, PAID_HOME_ON)).toEqual(ALL_BLOCKS);
  });

  it("free sees all blocks (the legacy `usps`-only trim no longer applies — block was eliminated in Wave-6)", () => {
    expect(visibleBlocksFor(free as never, PAID_HOME_ON)).toEqual(ALL_BLOCKS);
  });

  it("pro sees the trimmed paid-home list (hero image + shelves)", () => {
    expect(visibleBlocksFor(pro as never, PAID_HOME_ON)).toEqual(PAID_BLOCKS);
  });

  it("agency sees the trimmed paid-home list (hero image + shelves)", () => {
    expect(visibleBlocksFor(agency as never, PAID_HOME_ON)).toEqual(PAID_BLOCKS);
  });
});

describe("visibleBlocksFor — usp_popup_v1 flag (post-Wave-6 no-op on registry)", () => {
  // Wave 6: the in-page USPBand was eliminated, so usp_popup_v1 no
  // longer filters anything in the registry — its only remaining
  // purpose is controlling whether the standalone UspPopup modal
  // arms its scroll/exit-intent triggers (handled in NewHomePage).
  it.each([
    ["anonymous", anon],
    ["free",      free],
    ["pro",       pro],
    ["agency",    agency],
  ])("is a no-op for %s (registry no longer filters on it)", (_, user) => {
    expect(visibleBlocksFor(user as never, POPUP_ON))
      .toEqual(visibleBlocksFor(user as never, ALL_FLAGS_OFF));
  });
});

describe("visibleBlocksFor — paid_home + usp_popup_v1 (compose)", () => {
  it("anonymous: same as paid_home alone (usp_popup_v1 is a registry no-op)", () => {
    expect(visibleBlocksFor(anon as never, BOTH_ON)).toEqual(ALL_BLOCKS);
  });

  it("pro: paid_home trim applies, popup flag is a no-op", () => {
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

  it("composes with all flags on for paid: only hero + shelves remain", () => {
    const out = visibleBlocksFor(pro as never, ALL_FLAGS_ON);
    expect(out).toEqual(["hero", ...SIX_TOP_SHELVES]);
  });
});

describe("visibleBlocksFor — hero_v5 flag (Wave-6)", () => {
  // hero_v5 replaces both `hero` and `shoreline` for every tier — the
  // new editorial hero absorbs the destination picker via its 5 cards.
  it.each([
    ["anonymous", anon],
    ["free",      free],
    ["pro",       pro],
    ["agency",    agency],
  ])("swaps hero+shoreline for hero_v5 for %s", (_, user) => {
    const out = visibleBlocksFor(user as never, HERO_V5_ON);
    expect(out).toContain("hero_v5");
    expect(out).not.toContain("hero");
    expect(out).not.toContain("shoreline");
  });

  it("composes with usp_popup_v1: hero_v5 + featured remain, shoreline gone, popup-flag is a registry no-op", () => {
    const out = visibleBlocksFor(anon as never, {
      paid_home_variant_v1: false,
      usp_popup_v1:         true,
      hero_v4:              false,
      hero_v5:              true,
    });
    expect(out).toContain("hero_v5");
    expect(out).toContain("featured");
    expect(out).not.toContain("hero");
    expect(out).not.toContain("shoreline");
  });

  it("hero_v5 off (default): hero_v5 block never renders", () => {
    expect(visibleBlocksFor(anon as never, ALL_FLAGS_OFF)).not.toContain("hero_v5");
    expect(visibleBlocksFor(pro as never, PAID_HOME_ON)).not.toContain("hero_v5");
  });
});

describe("visibleBlocksFor — defensive defaults", () => {
  it("treats undefined user as anonymous (paid_home flag on)", () => {
    expect(visibleBlocksFor(undefined as never, PAID_HOME_ON)).toEqual(ALL_BLOCKS);
  });

  it("treats unknown plan as free (per gating.ts tierFor)", () => {
    // Post-Wave-6: free tier sees the same blocks as anonymous (the
    // `usps` block was eliminated, removing the old free-vs-anon delta).
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
