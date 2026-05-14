// Unit tests for the Wave-5 USP popup trigger logic. Pure function +
// localStorage-stamped suppression; armPassiveTriggers is integration-
// tested via the e2e spec (DOM events are not worth synthesizing here).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  decideArm,
  isWithinSuppressionWindow,
  markUspPopupDismissed,
  USP_DISMISSED_AT_KEY,
  _TESTING,
} from "./usp-popup-trigger";

type Storage = {
  data: Record<string, string>;
  getItem: (k: string) => string | null;
  setItem: (k: string, v: string) => void;
  removeItem: (k: string) => void;
  clear: () => void;
};

function makeStorage(): Storage {
  const data: Record<string, string> = {};
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = v; },
    removeItem: (k) => { delete data[k]; },
    clear: () => { for (const k of Object.keys(data)) delete data[k]; },
  };
}

let store: Storage;

beforeEach(() => {
  store = makeStorage();
  vi.stubGlobal("localStorage", store as never);
  // decideArm reads window.location when searchParams isn't passed; we
  // pass searchParams in every test so the global isn't needed, but
  // stub a minimal window so the SSR branch doesn't trip.
  vi.stubGlobal("window", { location: { search: "" }, innerWidth: 1280 } as never);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const anon = null;
const free = { plan: "free" as const };
const pro = { plan: "pro" as const };
const agency = { plan: "agency" as const };

describe("markUspPopupDismissed + isWithinSuppressionWindow", () => {
  it("isWithinSuppressionWindow is false before any dismissal", () => {
    expect(isWithinSuppressionWindow()).toBe(false);
  });

  it("returns true within the 7-day window after dismissal", () => {
    const t0 = 1_700_000_000_000;
    markUspPopupDismissed(t0);
    expect(store.data[USP_DISMISSED_AT_KEY]).toBe(String(t0));
    // 1 day later → still within window
    expect(isWithinSuppressionWindow(t0 + 86_400_000)).toBe(true);
    // 6.99 days later → still within
    expect(isWithinSuppressionWindow(t0 + 6.99 * 86_400_000)).toBe(true);
  });

  it("returns false past the 7-day window", () => {
    const t0 = 1_700_000_000_000;
    markUspPopupDismissed(t0);
    expect(isWithinSuppressionWindow(t0 + _TESTING.SUPPRESSION_DAYS * 86_400_000 + 1)).toBe(false);
  });

  it("handles clock skew (now < dismissedAt) by treating as not-suppressed", () => {
    const t0 = 1_700_000_000_000;
    markUspPopupDismissed(t0);
    expect(isWithinSuppressionWindow(t0 - 1000)).toBe(false);
  });
});

describe("decideArm — tier exclusion", () => {
  it("pro user → skip(paid_user)", () => {
    expect(decideArm({ user: pro, searchParams: new URLSearchParams("?upsell=1") }))
      .toEqual({ kind: "skip", reason: "paid_user" });
  });

  it("agency user → skip(paid_user)", () => {
    expect(decideArm({ user: agency, searchParams: new URLSearchParams("") }))
      .toEqual({ kind: "skip", reason: "paid_user" });
  });

  it("free user → eligible (continues evaluation)", () => {
    expect(decideArm({ user: free, searchParams: new URLSearchParams("") }))
      .toEqual({ kind: "arm" });
  });

  it("anonymous user → eligible", () => {
    expect(decideArm({ user: anon, searchParams: new URLSearchParams("") }))
      .toEqual({ kind: "arm" });
  });
});

describe("decideArm — URL params", () => {
  it("?upsell=1 fires url_param immediately for eligible users", () => {
    expect(decideArm({ user: free, searchParams: new URLSearchParams("?upsell=1") }))
      .toEqual({ kind: "fire_now", trigger: "url_param" });
  });

  it("?upsell=0 short-circuits even if the user would otherwise see the popup", () => {
    expect(decideArm({ user: free, searchParams: new URLSearchParams("?upsell=0") }))
      .toEqual({ kind: "skip", reason: "force_off" });
  });

  it("no upsell param → arm passive triggers", () => {
    expect(decideArm({ user: anon, searchParams: new URLSearchParams("?utm_source=foo") }))
      .toEqual({ kind: "arm" });
  });
});

describe("decideArm — suppression precedence", () => {
  it("suppression wins over arm (no popup for a recently-dismissed user)", () => {
    const t0 = 1_700_000_000_000;
    markUspPopupDismissed(t0);
    expect(decideArm({ user: free, searchParams: new URLSearchParams(""), now: t0 + 1000 }))
      .toEqual({ kind: "skip", reason: "suppressed" });
  });

  it("suppression wins over ?upsell=1 (dismissed users don't re-fire on URL re-entry)", () => {
    const t0 = 1_700_000_000_000;
    markUspPopupDismissed(t0);
    expect(decideArm({ user: free, searchParams: new URLSearchParams("?upsell=1"), now: t0 + 1000 }))
      .toEqual({ kind: "skip", reason: "suppressed" });
  });

  it("paid_user wins over suppression (skip-reason precedence: tier > suppression)", () => {
    const t0 = 1_700_000_000_000;
    markUspPopupDismissed(t0);
    expect(decideArm({ user: pro, searchParams: new URLSearchParams(""), now: t0 + 1000 }))
      .toEqual({ kind: "skip", reason: "paid_user" });
  });
});

describe("decideArm — defensive defaults", () => {
  it("treats undefined user as anonymous (eligible)", () => {
    expect(decideArm({ user: undefined as never, searchParams: new URLSearchParams("") }))
      .toEqual({ kind: "arm" });
  });

  it("treats unknown plan as free (per gating.ts)", () => {
    expect(
      decideArm({
        user: { plan: "mystery" as never },
        searchParams: new URLSearchParams(""),
      }),
    ).toEqual({ kind: "arm" });
  });
});
