// P2a — DiscoverFilter persistence helpers.
//
// The React hook (`useDiscoverFilterPersist`) is thin glue around
// `nextWriteForFilter` + a debounce timer; exercising the pure
// decision helper is enough to lock the skip/write contract. The hook
// itself gets observed via the e2e suite once it's wired to BrowsePage.

import { describe, expect, it } from "vitest";
import {
  getDiscoverFilterSeed,
  nextWriteForFilter,
} from "./use-discover-filter";

describe("getDiscoverFilterSeed", () => {
  it("returns null when URL already has filter params", () => {
    const app = {
      user: { profile: { discover_filters: { zones: ["el-tunco"] } } },
    };
    expect(getDiscoverFilterSeed(app, true)).toBeNull();
  });

  it("returns null for anonymous users (no Clerk record)", () => {
    expect(getDiscoverFilterSeed(null, false)).toBeNull();
    expect(getDiscoverFilterSeed({ user: null }, false)).toBeNull();
    expect(getDiscoverFilterSeed({ user: undefined }, false)).toBeNull();
  });

  it("returns null when the user has no persisted filter", () => {
    expect(getDiscoverFilterSeed({ user: { profile: {} } }, false)).toBeNull();
    expect(
      getDiscoverFilterSeed({ user: { profile: { discover_filters: {} } } }, false),
    ).toBeNull();
  });

  it("returns the deserialised filter when present + URL is empty", () => {
    const app = {
      user: {
        profile: {
          discover_filters: {
            zones: ["el-zonte", "el-tunco"],
            price_max: 500000,
            master_category: "beach",
          },
        },
      },
    };
    const seed = getDiscoverFilterSeed(app, false);
    expect(seed).not.toBeNull();
    expect([...(seed!.zones ?? new Set())].sort()).toEqual(["el-tunco", "el-zonte"]);
    expect(seed!.price_max).toBe(500000);
    expect(seed!.master_category).toBe("beach");
  });
});

describe("nextWriteForFilter", () => {
  it("returns the candidate when nothing is persisted yet", () => {
    expect(
      nextWriteForFilter(
        {},
        { zones: ["el-tunco"], price_max: 500000 },
        null,
      ),
    ).toEqual({ zones: ["el-tunco"], price_max: 500000 });
  });

  it("returns null when the candidate matches what's already persisted", () => {
    // Mount-time hydration + popstate URL reparse should never burn
    // a Clerk write — the candidate is the same blob we just hydrated
    // from.
    expect(
      nextWriteForFilter(
        { zones: ["el-tunco"] },
        { zones: ["el-tunco"] },
        null,
      ),
    ).toBeNull();
  });

  it("returns null when the candidate matches the last write we shipped", () => {
    // Post-write re-render: setUser brings the just-saved profile
    // back into scope and the effect re-runs; the lastWritten guard
    // catches it before another debounce fires.
    const lastWritten = JSON.stringify({ zones: ["el-tunco"] });
    expect(
      nextWriteForFilter({}, { zones: ["el-tunco"] }, lastWritten),
    ).toBeNull();
  });

  it("returns the candidate when persisted differs", () => {
    expect(
      nextWriteForFilter(
        { zones: ["el-tunco"] },
        { zones: ["el-tunco", "el-zonte"] },
        null,
      ),
    ).toEqual({ zones: ["el-tunco", "el-zonte"] });
  });

  it("treats a removed axis as a real change (not equal)", () => {
    expect(
      nextWriteForFilter(
        { zones: ["el-tunco"], price_max: 500000 },
        { price_max: 500000 },
        null,
      ),
    ).toEqual({ price_max: 500000 });
  });

  it("returns the candidate when lastWritten differs from persisted", () => {
    // Multi-tab scenario: another tab shipped a write we don't know
    // about (persisted ≠ lastWritten). We still want to honour the
    // user's current intent — write our value through.
    expect(
      nextWriteForFilter(
        { zones: ["el-zonte"] },
        { zones: ["el-tunco"] },
        JSON.stringify({ zones: [] }),
      ),
    ).toEqual({ zones: ["el-tunco"] });
  });
});
