// Rewritten homepage shell — composes the five Phase 4B components
// in the section order specified by the rewrite brief:
//
//   1. Hero            — copy-led + email form
//   2. ProofRow        — "This week's top 3 deals"
//   3. CategoryGrid    — Beach × {homes,condos,land} + Lake × same
//   4. DiscoveryPills  — All / ★ Top rated / Under $250K / Gated / Waterfront
//   5. USPRow          — 3-column "Why Pulpo"
//
// Rendered by app.jsx when VITE_NEW_HOMEPAGE=1 (see the flag check
// there); otherwise the legacy HomePage in pages.jsx renders. The
// shell itself owns NO state — every component reads from useListings()
// / loadFeaturedJson() / app context independently. This keeps the
// shell trivial to swap during the rollout.
//
// The full Discover-shelves stack is intentionally NOT rendered here.
// Per the rewrite plan Q6, shelves moved to the BrowsePage (Phase 5).
// Keeping the homepage tight: hero + proof + category + pills + USPs
// is enough surface for cold-visitor conversion; warm visitors who
// want shelves click through to /browse.
import React, { useEffect } from "react";
import { Hero, ProofRow, CategoryGrid, DiscoveryPills, USPRow } from "./index.js";
import { ShelfRail } from "./ShelfRail.jsx";
import { decideShouldShowUpsell } from "../lib/upsell-config.ts";

/**
 * @param {object} props
 * @param {object} props.app  — App state with goBrowse(...) + openListing(...)
 */
export function NewHomePage({ app }) {
  const locale = app.locale;

  // Pro upsell modal trigger (PR-B.5, ported in Phase 9 cutover from
  // the deleted legacy HomePage). decideShouldShowUpsell reads the
  // URL's campaign params + Pro state + 7-day suppression and decides
  // show/no-show. Pure function — same source of truth as the test
  // suite. The trigger fires once on mount; subsequent route changes
  // don't re-evaluate.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!app.openProUpsellModal) return;
    let urls;
    try { urls = new URLSearchParams(window.location.search); } catch { return; }
    const decision = decideShouldShowUpsell({
      searchParams: urls,
      isProUser: !!(app.user && app.user.plan === "pro"),
    });
    if (!decision.show) return;
    // Collect a small payload so the modal can show context (e.g. the
    // referral code) + so telemetry can attribute conversions.
    const utms = {};
    for (const k of ["utm_source", "utm_medium", "utm_campaign"]) {
      const v = urls.get(k);
      if (v) utms[k] = v;
    }
    app.openProUpsellModal({
      trigger: decision.trigger,
      urlCode: urls.get("code") || null,
      utms,
    });
    // Mount-only — re-running on a routeParams tweak would re-fire
    // after the user dismisses the modal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="new-homepage">
      <Hero locale={locale} />
      <ProofRow app={app} locale={locale} />
      <CategoryGrid app={app} locale={locale} />
      <DiscoveryPills app={app} locale={locale} sourcePage="homepage" />
      <USPRow locale={locale} />
      {/* Activity shelves — 2 in the reduced config: new_this_week +
          price_drops. ShelfRail self-hides empty shelves + the whole
          rail when nothing qualifies, so a thin catalog won't render
          a broken section. */}
      <ShelfRail app={app} locale={locale} />
    </div>
  );
}
