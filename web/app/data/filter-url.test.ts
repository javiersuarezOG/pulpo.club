// hasFilterParamsInURL — the URL-vs-Clerk precedence test. When ANY
// known filter param sits on the URL, the URL wins and the Clerk
// persisted filter is NOT hydrated as the BrowsePage seed.

import { describe, expect, it } from "vitest";
import { FILTER_URL_KEYS, hasFilterParamsInURL } from "./filter-url";

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
