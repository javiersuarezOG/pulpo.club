// Feature-flag read semantics — boolean kill-switch + multivariate A/B
// variant, plus the ?ff_<key>= URL escape hatch both share. PostHog isn't
// loaded in unit context (the client singleton is null), so these cover
// the override branches and the no-PostHog fallback — the exact paths
// Playwright and cold-load traffic hit.

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  readFeatureFlag,
  readFeatureVariant,
} from "./feature-flag";

function setSearch(search: string) {
  vi.stubGlobal("window", { location: { search } } as never);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("readFeatureFlag — boolean override", () => {
  it("?ff_<key>=1 forces true, =0 forces false", () => {
    setSearch("?ff_cta_routing_v2=1");
    expect(readFeatureFlag("cta_routing_v2", false)).toBe(true);
    setSearch("?ff_cta_routing_v2=0");
    expect(readFeatureFlag("cta_routing_v2", true)).toBe(false);
  });

  it("falls back when no override and PostHog isn't loaded", () => {
    setSearch("");
    expect(readFeatureFlag("some_flag", true)).toBe(true);
    expect(readFeatureFlag("some_flag", false)).toBe(false);
  });
});

describe("readFeatureVariant — multivariate override", () => {
  it("?ff_<key>=<variant> forces the named arm", () => {
    setSearch("?ff_popup_copy=variant_b");
    expect(readFeatureVariant("popup_copy", "control")).toBe("variant_b");
  });

  it("reserves 1/0 for the boolean hatch — they do NOT become a variant", () => {
    // A variant read seeing ?ff_x=1 must ignore it (that's the boolean
    // override's namespace) and return the fallback arm instead.
    setSearch("?ff_popup_copy=1");
    expect(readFeatureVariant("popup_copy", "control")).toBe("control");
    setSearch("?ff_popup_copy=0");
    expect(readFeatureVariant("popup_copy", "control")).toBe("control");
  });

  it("falls back to the control arm when no override and PostHog isn't loaded", () => {
    setSearch("");
    expect(readFeatureVariant("popup_copy", "control")).toBe("control");
  });

  it("is inert (returns fallback) in SSR / no-window", () => {
    vi.stubGlobal("window", undefined as never);
    expect(readFeatureVariant("popup_copy", "control")).toBe("control");
    expect(readFeatureFlag("popup_copy", true)).toBe(true);
  });
});
