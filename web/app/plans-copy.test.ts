// Capability contract for the /plans Free card.
//
// The two-state model (2026-06-08) gates listing detail + saves behind Pro,
// with ONE Free exception: this week's top 3 ranked picks open in full
// (see web/app/lib/free-view + app.jsx openListing). The /plans Free card
// must describe exactly that — never a capability the gates don't grant.
//
// History: the Free card shipped "8 detail views per month" + "Save up to
// 10 listings" long after both became Pro-only — a pricing page that lied
// on the conversion surface. This guard fails if any Free feature line
// re-introduces a Pro-gated promise, in EITHER locale.

import { describe, it, expect } from "vitest";
import { UI_STRINGS, LOCALES, t } from "./i18n.jsx";

// Every Free plan feature line (both locales), as actually rendered.
function freeFeatureStrings(): string[] {
  const keys = Object.keys(UI_STRINGS).filter((k) => k.startsWith("plans.free.feat."));
  const out: string[] = [];
  for (const key of keys) {
    for (const loc of LOCALES) out.push(t(key, loc).toLowerCase());
  }
  return out;
}

describe("/plans Free card — capability contract", () => {
  it("advertises at least the three real Free capabilities", () => {
    const keys = Object.keys(UI_STRINGS).filter((k) => k.startsWith("plans.free.feat."));
    expect(keys).toContain("plans.free.feat.browsing");      // unlimited card browsing
    expect(keys).toContain("plans.free.feat.top3_detail");   // full detail on the weekly top 3
    expect(keys).toContain("plans.free.feat.weekly_email");  // weekly top-3 email
  });

  it("never promises SAVES (a Pro-only capability)", () => {
    // Saves return 403 pro_required for non-Pro (api/saves.js). The Free
    // card must not imply the user can save listings.
    const banned = [/\bsave\b/, /\bsaves\b/, /\bsaving\b/, /\bguarda\b/, /\bguardar\b/];
    for (const s of freeFeatureStrings()) {
      for (const re of banned) {
        expect(s, `Free feature copy promises saves: "${s}"`).not.toMatch(re);
      }
    }
  });

  it("never promises a metered/numeric detail-view allowance", () => {
    // Free detail is NOT metered — it's exactly the top 3. A line like
    // "8 detail views per month" / "8 fichas detalladas al mes" is a lie.
    const meteredDetail = [
      /\d+\s*detail views?/,
      /\d+\s*fichas/,
    ];
    for (const s of freeFeatureStrings()) {
      for (const re of meteredDetail) {
        expect(s, `Free feature copy promises metered detail views: "${s}"`).not.toMatch(re);
      }
    }
  });
});
