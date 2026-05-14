// Unit tests for campaign-param capture + persistence. Wave-2 added
// `urlCode` to the sessionStorage-persisted set so a promo code landing
// at `/?code=PULPO20` survives a same-session navigation to `/plans`
// before the user clicks Upgrade. UTMs already worked this way; the test
// covers both to prevent the precedence rule from drifting.
//
// No jsdom dependency — vitest's stubGlobal wires synthetic window +
// sessionStorage. We don't need a real DOM here, just the two reads
// captureCampaignParams() makes.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { captureCampaignParams } from "./campaign";

type StorageShape = {
  data: Record<string, string>;
  getItem: (k: string) => string | null;
  setItem: (k: string, v: string) => void;
  removeItem: (k: string) => void;
  clear: () => void;
};

function makeStorage(): StorageShape {
  const data: Record<string, string> = {};
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = v; },
    removeItem: (k) => { delete data[k]; },
    clear: () => { for (const k of Object.keys(data)) delete data[k]; },
  };
}

function setLocation(search: string) {
  vi.stubGlobal("window", { location: { search } } as never);
}

let store: StorageShape;

beforeEach(() => {
  store = makeStorage();
  vi.stubGlobal("sessionStorage", store as never);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("captureCampaignParams — urlCode persistence (Wave 2)", () => {
  it("returns the code from the URL and persists it to sessionStorage", () => {
    setLocation("?code=pulpo20");
    const out = captureCampaignParams();
    expect(out.urlCode).toBe("PULPO20"); // uppercased + trimmed
    expect(store.data["pulpo-code"]).toBe("PULPO20");
  });

  it("falls back to sessionStorage when the URL has no code", () => {
    store.data["pulpo-code"] = "REDDIT01";
    setLocation("");
    const out = captureCampaignParams();
    expect(out.urlCode).toBe("REDDIT01");
  });

  it("URL takes precedence over sessionStorage (newer campaign wins)", () => {
    store.data["pulpo-code"] = "OLD_DEAL";
    setLocation("?code=NEW_DEAL");
    const out = captureCampaignParams();
    expect(out.urlCode).toBe("NEW_DEAL");
    expect(store.data["pulpo-code"]).toBe("NEW_DEAL"); // overwritten
  });

  it("returns empty string when neither URL nor sessionStorage has a code", () => {
    setLocation("");
    const out = captureCampaignParams();
    expect(out.urlCode).toBe("");
  });

  it("trims + uppercases the URL code before persisting", () => {
    setLocation("?code=%20pulpo20%20");
    const out = captureCampaignParams();
    expect(out.urlCode).toBe("PULPO20");
    expect(store.data["pulpo-code"]).toBe("PULPO20");
  });
});

describe("captureCampaignParams — UTM persistence (unchanged)", () => {
  it("URL UTM wins over stored value (pre-existing behavior, regression guard)", () => {
    store.data["pulpo-utm_source"] = "old_source";
    setLocation("?utm_source=newsletter&utm_campaign=launch");
    const out = captureCampaignParams();
    expect(out.utms.utm_source).toBe("newsletter");
    expect(out.utms.utm_campaign).toBe("launch");
    expect(store.data["pulpo-utm_source"]).toBe("newsletter");
  });

  it("falls back to sessionStorage when URL has no UTM", () => {
    store.data["pulpo-utm_source"] = "reddit";
    setLocation("");
    const out = captureCampaignParams();
    expect(out.utms.utm_source).toBe("reddit");
  });
});

describe("captureCampaignParams — combined snapshot", () => {
  it("returns code + utms + cancelled + upsellOverride in one pass", () => {
    setLocation("?code=PULPO50&utm_source=ig&cancelled=1&upsell=1");
    const out = captureCampaignParams();
    expect(out.urlCode).toBe("PULPO50");
    expect(out.utms.utm_source).toBe("ig");
    expect(out.isCancelled).toBe(true);
    expect(out.upsellOverride).toBe("1");
  });
});
