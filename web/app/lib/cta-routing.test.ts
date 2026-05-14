// Unit tests for the Wave-1 CTA routing matrix. Pure-function table
// tests: every (ctaId, tier) pair maps to the expected Branch. If this
// file goes red, downstream PostHog dashboards filtering on
// cta_routed.branch will misclassify clicks — treat the matrix below
// as the spec, not the implementation.
//
// Vitest auto-discovers this file via the default glob. No vitest
// config needed because the module under test is React-free.

import { describe, expect, it } from "vitest";
import {
  routeCtaForState,
  type Branch,
  type CtaId,
} from "./cta-routing";

type TierLabel = "anonymous" | "free" | "pro" | "agency";
type User = { plan?: TierLabel | "anonymous" } | null;

const anon: User = null;
const free: User = { plan: "free" };
const pro: User = { plan: "pro" };
const agency: User = { plan: "agency" };

// One row per CTA × tier. Reads top-to-bottom should match the Wave-1
// plan and the inline comments in lib/cta-routing.ts.
const matrix: Array<[CtaId, User, Branch, string]> = [
  // header_primary — paid users never see this CTA in Wave 4, but the
  // matrix must answer for them so the runtime is total.
  ["header_primary", anon,   "stripe_checkout", "anon hits hero header CTA"],
  ["header_primary", free,   "paywall",         "free hits hero header CTA"],
  ["header_primary", pro,    "passthrough",     "pro hits hero header CTA (no-op until Wave 4 hides it)"],
  ["header_primary", agency, "passthrough",     "agency hits hero header CTA"],

  ["hero_primary",   anon,   "stripe_checkout", "anon hits hero primary"],
  ["hero_primary",   free,   "paywall",         "free hits hero primary"],
  ["hero_primary",   pro,    "passthrough",     "pro hits hero primary"],
  ["hero_primary",   agency, "passthrough",     "agency hits hero primary"],

  // hero_just_in: pill names a real listing — paid + free open it.
  ["hero_just_in",   anon,   "free_signup",     "anon clicks Just In pill"],
  ["hero_just_in",   free,   "passthrough",     "free clicks Just In pill (opens listing)"],
  ["hero_just_in",   pro,    "passthrough",     "pro clicks Just In pill (opens listing)"],
  ["hero_just_in",   agency, "passthrough",     "agency clicks Just In pill"],

  // featured_deal: hardcoded copy, no real target. Anon-only funnel hook.
  ["featured_deal",  anon,   "free_signup",     "anon clicks FeaturedDeal"],
  ["featured_deal",  free,   "passthrough",     "free clicks FeaturedDeal (no-op)"],
  ["featured_deal",  pro,    "passthrough",     "pro clicks FeaturedDeal (no-op)"],
  ["featured_deal",  agency, "passthrough",     "agency clicks FeaturedDeal"],

  // newsletter_activation: only the upgrade CTA flows through here.
  ["newsletter_activation", anon,   "login_ui",   "anon clicks newsletter upgrade"],
  ["newsletter_activation", free,   "paywall",    "free clicks newsletter upgrade"],
  ["newsletter_activation", pro,    "passthrough","pro clicks newsletter upgrade (UI not shown)"],
  ["newsletter_activation", agency, "passthrough","agency clicks newsletter upgrade"],

  // shelf_card: hardcoded editorial placeholders today.
  ["shelf_card",     anon,   "free_signup",     "anon clicks shelf card"],
  ["shelf_card",     free,   "passthrough",     "free clicks shelf card (no real listing yet)"],
  ["shelf_card",     pro,    "passthrough",     "pro clicks shelf card"],
  ["shelf_card",     agency, "passthrough",     "agency clicks shelf card"],

  // broker_outbound: paid sees the link; non-paid sees an upgrade CTA
  // (handled by detail CTA bar's existing branch — matrix is defensive).
  ["broker_outbound", anon,   "paywall",        "anon would hit broker (CTA bar shows upgrade)"],
  ["broker_outbound", free,   "paywall",        "free would hit broker (CTA bar shows upgrade)"],
  ["broker_outbound", pro,    "passthrough",    "pro clicks broker outbound (link opens)"],
  ["broker_outbound", agency, "passthrough",    "agency clicks broker outbound"],

  // favorites_action: anon save chains to free signup.
  ["favorites_action", anon,   "free_signup",   "anon clicks heart"],
  ["favorites_action", free,   "passthrough",   "free clicks heart (toggles save)"],
  ["favorites_action", pro,    "passthrough",   "pro clicks heart"],
  ["favorites_action", agency, "passthrough",   "agency clicks heart"],

  // account_entry: anon profile click → login modal.
  ["account_entry",   anon,   "login_ui",      "anon clicks profile nav"],
  ["account_entry",   free,   "passthrough",   "free clicks profile nav (navigates to /account)"],
  ["account_entry",   pro,    "passthrough",   "pro clicks profile nav"],
  ["account_entry",   agency, "passthrough",   "agency clicks profile nav"],
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
    expect(routeCtaForState("hero_primary", undefined as never)).toBe("stripe_checkout");
  });

  it("treats unknown plan as free (per gating.ts tierFor)", () => {
    expect(
      routeCtaForState("hero_primary", { plan: "mystery_tier" as never } as never),
    ).toBe("paywall");
  });
});
