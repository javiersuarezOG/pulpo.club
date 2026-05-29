// P2a — DiscoverFilter converters + accessor.
//
// Pure converters between BrowsePage's in-memory shape (Set-backed
// axes) and the JSON-safe storage shape that goes to Clerk. The hook
// (useDiscoverFilter, separate file) composes these with the Clerk
// write surface; this spec just locks the converter contract.

import { describe, expect, it } from "vitest";
import {
  discoverFilterEqual,
  discoverToStorage,
  readDiscoverFilter,
  storageToDiscover,
  type DiscoverFilter,
  type DiscoverInMemoryFilter,
} from "./user-profile";

describe("discoverToStorage", () => {
  it("drops empty Set axes (missing key = 'no opinion' on the server)", () => {
    const inMem: DiscoverInMemoryFilter = {
      zones: new Set(),
      land_types: new Set(),
      features: new Set(),
      infra: new Set(),
      status: new Set(),
      discovery_tags: new Set(),
      price_min: 0,
      price_max: null,
      size_min: 0,
      readiness: 0,
      rank_max: null,
      master_category: null,
      subcategory: null,
    };
    expect(discoverToStorage(inMem)).toEqual({});
  });

  it("serialises populated Set axes to sorted string arrays", () => {
    const inMem: DiscoverInMemoryFilter = {
      zones: new Set(["el-zonte", "el-tunco"]),
      features: new Set(["beachfront", "ocean_view"]),
    };
    expect(discoverToStorage(inMem)).toEqual({
      zones: ["el-tunco", "el-zonte"],            // alphabetical
      features: ["beachfront", "ocean_view"],
    });
  });

  it("preserves numeric axes only when off-default", () => {
    const inMem: DiscoverInMemoryFilter = {
      price_min: 50000,
      price_max: 500000,
      size_min: 1000,
      readiness: 2,
      rank_max: 10,
    };
    expect(discoverToStorage(inMem)).toEqual({
      price_min: 50000,
      price_max: 500000,
      size_min: 1000,
      readiness: 2,
      rank_max: 10,
    });
  });

  it("preserves enum axes only when explicitly set", () => {
    expect(discoverToStorage({ master_category: "beach", subcategory: "land" })).toEqual({
      master_category: "beach",
      subcategory: "land",
    });
    // Bogus values are dropped (defends against a stale URL or hand-
    // edited Clerk blob slipping past the BrowsePage type).
    expect(
      discoverToStorage({
        master_category: "garbage" as unknown as "beach",
        subcategory: "nonsense" as unknown as "land",
      }),
    ).toEqual({});
  });

  it("strips tuning knobs (weights / score_min / photos / include_incomplete)", () => {
    const inMem: DiscoverInMemoryFilter = {
      zones: new Set(["el-tunco"]),
      weights: { value: 50, location: 30, momentum: 20 },
      score_min: 75,
      photos: "with",
      include_incomplete: true,
    };
    const out = discoverToStorage(inMem);
    expect(out).toEqual({ zones: ["el-tunco"] });
    // Belt-and-suspenders: the tuning keys must literally not appear.
    expect(Object.keys(out)).not.toContain("weights");
    expect(Object.keys(out)).not.toContain("score_min");
    expect(Object.keys(out)).not.toContain("photos");
    expect(Object.keys(out)).not.toContain("include_incomplete");
  });

  it("is deterministic — equivalent inputs produce identical JSON", () => {
    const a: DiscoverInMemoryFilter = {
      zones: new Set(["el-zonte", "el-tunco"]),
      features: new Set(["ocean_view", "beachfront"]),
    };
    const b: DiscoverInMemoryFilter = {
      zones: new Set(["el-tunco", "el-zonte"]),
      features: new Set(["beachfront", "ocean_view"]),
    };
    expect(JSON.stringify(discoverToStorage(a))).toBe(JSON.stringify(discoverToStorage(b)));
  });
});

describe("storageToDiscover", () => {
  it("round-trips through discoverToStorage without loss", () => {
    const inMem: DiscoverInMemoryFilter = {
      zones: new Set(["el-zonte"]),
      land_types: new Set(["residential"]),
      features: new Set(["beachfront"]),
      infra: new Set(["power", "water"]),
      status: new Set(["price_drop"]),
      discovery_tags: new Set(["top_rated"]),
      price_min: 50000,
      price_max: 500000,
      size_min: 1000,
      readiness: 3,
      rank_max: 10,
      master_category: "beach",
      subcategory: "land",
    };
    const stored = discoverToStorage(inMem);
    const back = storageToDiscover(stored);
    // Sets compare by content — convert both sides to sorted arrays.
    for (const axis of ["zones", "land_types", "features", "infra", "status", "discovery_tags"] as const) {
      expect([...(back[axis] ?? new Set())].sort()).toEqual([...(inMem[axis] ?? new Set())].sort());
    }
    expect(back.price_min).toBe(inMem.price_min);
    expect(back.price_max).toBe(inMem.price_max);
    expect(back.size_min).toBe(inMem.size_min);
    expect(back.readiness).toBe(inMem.readiness);
    expect(back.rank_max).toBe(inMem.rank_max);
    expect(back.master_category).toBe(inMem.master_category);
    expect(back.subcategory).toBe(inMem.subcategory);
  });

  it("returns sensible defaults for an empty storage blob", () => {
    const out = storageToDiscover({});
    expect(out.zones?.size).toBe(0);
    expect(out.price_min).toBe(0);
    expect(out.price_max).toBeNull();
    expect(out.master_category).toBeNull();
    expect(out.subcategory).toBeNull();
  });

  it("defensively coerces non-string array entries (hand-edited Clerk blob)", () => {
    const bogus: DiscoverFilter = {
      zones: ["el-tunco", 42 as unknown as string, null as unknown as string, "el-zonte"],
    };
    const out = storageToDiscover(bogus);
    expect([...(out.zones ?? new Set())].sort()).toEqual(["el-tunco", "el-zonte"]);
  });

  it("coerces malformed enums to null (stale Clerk row)", () => {
    const bogus: DiscoverFilter = {
      master_category: "ocean" as unknown as "beach",
      subcategory: "tents" as unknown as "homes",
    };
    const out = storageToDiscover(bogus);
    expect(out.master_category).toBeNull();
    expect(out.subcategory).toBeNull();
  });
});

describe("readDiscoverFilter", () => {
  it("returns {} for a missing user", () => {
    expect(readDiscoverFilter(null)).toEqual({});
    expect(readDiscoverFilter(undefined)).toEqual({});
  });

  it("returns {} when profile.discover_filters is missing", () => {
    expect(readDiscoverFilter({ profile: {} })).toEqual({});
  });

  it("returns the stored discover_filters block", () => {
    const user = {
      profile: {
        discover_filters: { zones: ["el-tunco"], price_max: 500000 },
      },
    };
    expect(readDiscoverFilter(user)).toEqual({
      zones: ["el-tunco"],
      price_max: 500000,
    });
  });
});

describe("discoverFilterEqual", () => {
  it("treats structurally identical filters as equal", () => {
    expect(discoverFilterEqual({ zones: ["el-tunco"] }, { zones: ["el-tunco"] })).toBe(true);
  });
  it("notices a differing axis", () => {
    expect(discoverFilterEqual({ price_max: 500000 }, { price_max: 250000 })).toBe(false);
  });
  it("treats a missing axis vs an explicit empty array differently", () => {
    // Belt-and-suspenders: discoverToStorage drops empty axes, so we
    // should never actually observe this — but the equality helper
    // shouldn't paper over a discrepancy if it sneaks in.
    expect(discoverFilterEqual({}, { zones: [] })).toBe(false);
  });
});
