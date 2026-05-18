// Unit tests for the CTA routing matrix. Pure-function table tests:
// every (ctaId, tier) pair maps to the expected Branch. If this file
// goes red, downstream PostHog dashboards filtering on
// cta_routed.branch will misclassify clicks — treat the matrix below
// as the spec, not the implementation.
//
// Post-Wave-5 update: anon AND free for conversion CTAs (hero, header,
// featured, shelf, favorites, just_in) now route to `free_month_modal`.
// Paid tier behavior unchanged. Account/broker/newsletter not affected.

import { describe, expect, it, vi } from "vitest";
import {
  routeCtaForState,
  dispatchCentralBranch,
  type AppLike,
  type Branch,
  type CtaId,
} from "./cta-routing";

type TierLabel = "anonymous" | "free" | "pro" | "agency";
type User = { plan?: TierLabel | "anonymous" } | null;

const anon: User = null;
const free: User = { plan: "free" };
const pro: User = { plan: "pro" };
const agency: User = { plan: "agency" };

// One row per CTA × tier.
const matrix: Array<[CtaId, User, Branch, string]> = [
  // header_primary — conversion CTA for anon + free.
  ["header_primary", anon,   "free_month_modal", "anon hits hero header CTA"],
  ["header_primary", free,   "free_month_modal", "free hits hero header CTA"],
  ["header_primary", pro,    "passthrough",      "pro hits hero header CTA (no-op)"],
  ["header_primary", agency, "passthrough",      "agency hits hero header CTA"],

  ["hero_primary",   anon,   "free_month_modal", "anon hits hero primary"],
  ["hero_primary",   free,   "free_month_modal", "free hits hero primary"],
  ["hero_primary",   pro,    "passthrough",      "pro hits hero primary"],
  ["hero_primary",   agency, "passthrough",      "agency hits hero primary"],

  // hero_just_in: anon + free → modal; paid → passthrough (opens listing).
  ["hero_just_in",   anon,   "free_month_modal", "anon clicks Just In pill"],
  ["hero_just_in",   free,   "free_month_modal", "free clicks Just In pill"],
  ["hero_just_in",   pro,    "passthrough",      "pro clicks Just In pill (opens listing)"],
  ["hero_just_in",   agency, "passthrough",      "agency clicks Just In pill"],

  // featured_deal: anon + free → modal; paid → passthrough (opens resolved listing).
  ["featured_deal",  anon,   "free_month_modal", "anon clicks FeaturedDeal"],
  ["featured_deal",  free,   "free_month_modal", "free clicks FeaturedDeal"],
  ["featured_deal",  pro,    "passthrough",      "pro clicks FeaturedDeal"],
  ["featured_deal",  agency, "passthrough",      "agency clicks FeaturedDeal"],

  // newsletter_activation: unchanged — settings-page-only CTA, modal would be OOC.
  ["newsletter_activation", anon,   "login_ui",     "anon clicks newsletter upgrade"],
  ["newsletter_activation", free,   "paywall",      "free clicks newsletter upgrade"],
  ["newsletter_activation", pro,    "passthrough",  "pro clicks newsletter upgrade (UI not shown)"],
  ["newsletter_activation", agency, "passthrough",  "agency clicks newsletter upgrade"],

  // shelf_card: anon + free → modal; paid → passthrough (opens listing if real).
  ["shelf_card",     anon,   "free_month_modal", "anon clicks shelf card"],
  ["shelf_card",     free,   "free_month_modal", "free clicks shelf card"],
  ["shelf_card",     pro,    "passthrough",      "pro clicks shelf card"],
  ["shelf_card",     agency, "passthrough",      "agency clicks shelf card"],

  // broker_outbound: paid sees the link; non-paid sees an upgrade CTA
  // (handled by detail CTA bar's existing branch — matrix is defensive).
  ["broker_outbound", anon,   "paywall",        "anon would hit broker (CTA bar shows upgrade)"],
  ["broker_outbound", free,   "paywall",        "free would hit broker (CTA bar shows upgrade)"],
  ["broker_outbound", pro,    "passthrough",    "pro clicks broker outbound"],
  ["broker_outbound", agency, "passthrough",    "agency clicks broker outbound"],

  // favorites_action: anon + free → modal; paid → toggle save.
  ["favorites_action", anon,   "free_month_modal", "anon clicks heart"],
  ["favorites_action", free,   "free_month_modal", "free clicks heart"],
  ["favorites_action", pro,    "passthrough",      "pro clicks heart"],
  ["favorites_action", agency, "passthrough",      "agency clicks heart"],

  // account_entry: unchanged — modal would be hostile UX on nav click.
  ["account_entry",   anon,   "login_ui",       "anon clicks profile nav"],
  ["account_entry",   free,   "passthrough",    "free clicks profile nav"],
  ["account_entry",   pro,    "passthrough",    "pro clicks profile nav"],
  ["account_entry",   agency, "passthrough",    "agency clicks profile nav"],
];

describe("routeCtaForState — matrix", () => {
  for (const [ctaId, user, expected, label] of matrix) {
    it(`${ctaId} × ${user?.plan ?? "anonymous"} → ${expected} (${label})`, () => {
      expect(routeCtaForState(ctaId, user as never)).toBe(expected);
    });
  }
});

describe("routeCtaForState — defensive defaults", () => {
  it("treats undefined user as anonymous", () => {
    expect(routeCtaForState("hero_primary", undefined as never)).toBe("free_month_modal");
  });

  it("treats unknown plan as free (per gating.ts tierFor)", () => {
    expect(
      routeCtaForState("hero_primary", { plan: "mystery_tier" as never } as never),
    ).toBe("free_month_modal");
  });
});

describe("dispatchCentralBranch — free_month_modal", () => {
  it("calls app.openFreeMonthModal with the supplied trigger", async () => {
    const openFreeMonthModal = vi.fn();
    const app: AppLike = { openFreeMonthModal };
    const handled = await dispatchCentralBranch("free_month_modal", app, {
      trigger: "shelf_card",
    });
    expect(handled).toBe(true);
    expect(openFreeMonthModal).toHaveBeenCalledTimes(1);
    expect(openFreeMonthModal).toHaveBeenCalledWith({ trigger: "shelf_card" });
  });

  it("defaults trigger to hero_cta when none supplied", async () => {
    const openFreeMonthModal = vi.fn();
    const app: AppLike = { openFreeMonthModal };
    await dispatchCentralBranch("free_month_modal", app);
    expect(openFreeMonthModal).toHaveBeenCalledWith({ trigger: "hero_cta" });
  });

  it("returns true even when app.openFreeMonthModal is absent (defensive no-op)", async () => {
    const handled = await dispatchCentralBranch("free_month_modal", {}, {
      trigger: "hero_cta",
    });
    expect(handled).toBe(true);
  });
});
