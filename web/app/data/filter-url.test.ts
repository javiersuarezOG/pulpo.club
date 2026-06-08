// hasFilterParamsInURL — the URL-vs-Clerk precedence test. When ANY
// known filter param sits on the URL, the URL wins and the Clerk
// persisted filter is NOT hydrated as the BrowsePage seed.

import { describe, expect, it } from "vitest";
import {
  FILTER_URL_KEYS,
  hasFilterParamsInURL,
  readFilterFromURL,
  readSortFromURL,
  readViewFromURL,
  type FilterShape,
} from "./filter-url";

function baseFilters(): FilterShape {
  return {
    zones: new Set(),
    land_types: new Set(),
    features: new Set(),
    infra: new Set(),
    status: new Set(),
    price_min: 0,
    price_max: null,
    size_min: 0,
    readiness: 0,
    rank_max: null,
    master_category: null,
    subcategory: null,
    discovery_tags: new Set(),
    include_incomplete: false,
    query: "",
  };
}

describe("hasFilterParamsInURL", () => {
  it("returns false for an empty search string", () => {
    expect(hasFilterParamsInURL("")).toBe(false);
    expect(hasFilterParamsInURL("?")).toBe(false);
  });

  it("returns false when only non-filter params are present", () => {
    // dev/debug/utm survive but don't count as filter intent.
    expect(hasFilterParamsInURL("?dev=1&utm_source=test&debug=1")).toBe(false);
    // `cat` is the category pill — out of scope for the filter seed
    // because buildFiltersForCategory expands it into baseDefaults
    // independently.
    expect(hasFilterParamsInURL("?cat=land_with_water")).toBe(false);
    // `sort` is its own URL key, separately handled.
    expect(hasFilterParamsInURL("?sort=recent")).toBe(false);
  });

  it("returns true when any known filter key is present", () => {
    for (const key of FILTER_URL_KEYS) {
      expect(hasFilterParamsInURL(`?${key}=anything`), `key=${key}`).toBe(true);
    }
  });

  it("returns true for a realistic shared-link URL", () => {
    expect(
      hasFilterParamsInURL("?features=beachfront&pmax=500000&sort=recent"),
    ).toBe(true);
  });

  it("ignores tuning-knob params (wv / wl / wm / score_min / inc)", () => {
    // These ARE persisted in the URL but aren't user-facing "what to
    // find" axes; they tune how the catalogue reads. The Clerk
    // persistence layer doesn't round-trip them either.
    expect(hasFilterParamsInURL("?wv=50&wl=30&wm=20")).toBe(false);
    expect(hasFilterParamsInURL("?score_min=75")).toBe(false);
    expect(hasFilterParamsInURL("?inc=1")).toBe(false);
  });
});

// PR-7 (WS4) — view param + the cross-param coexistence guard the plan
// flags as critical: cat / sort / q / filter params / view must not
// erase each other on read.
describe("readViewFromURL", () => {
  it("defaults when absent or invalid; reads valid views", () => {
    expect(readViewFromURL("", "cards")).toBe("cards");
    expect(readViewFromURL("?view=map", "cards")).toBe("map");
    expect(readViewFromURL("?view=table", "cards")).toBe("table");
    expect(readViewFromURL("?view=bogus", "cards")).toBe("cards");
  });

  it("view is NOT a filter key — a bare ?view=map must not trigger the filter seed", () => {
    expect(hasFilterParamsInURL("?view=map")).toBe(false);
    expect(FILTER_URL_KEYS).not.toContain("view");
  });
});

describe("URL param coexistence (cat + sort + q + filters + view)", () => {
  it("every param survives a combined read; none clobbers another", () => {
    const search = "?cat=beach&sort=price_asc&q=tunco&pmax=100000&zones=El%20Tunco&view=map";
    const f = readFilterFromURL(search, baseFilters());
    expect(f.price_max).toBe(100000);
    expect([...f.zones]).toEqual(["El Tunco"]);
    expect(f.query).toBe("tunco");
    expect(readSortFromURL(search, "recent")).toBe("price_asc");
    expect(readViewFromURL(search, "cards")).toBe("map");
    // pmax + zones present → filter seed should fire.
    expect(hasFilterParamsInURL(search)).toBe(true);
  });

  it("a query-only URL keeps q and leaves view at its default", () => {
    const search = "?q=beachfront";
    expect(readFilterFromURL(search, baseFilters()).query).toBe("beachfront");
    expect(readViewFromURL(search, "cards")).toBe("cards");
  });
});
