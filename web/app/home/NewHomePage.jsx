// Homepage v2 — editorial coastal-index design.
//
// Sections, top to bottom:
//   1. HomepageHeader   — wordmark + nav + Start free month CTA + mobile sheet
//   2. HeroV2           — H1 with serif-italic "ranked.", CTAs, CSS-only newsletter preview
//   3. FeaturedDeal     — single editorial card between hero and USPs
//   4. USPBand          — "For subscribers only" + 3 cards on white
//   5. PickShoreline    — Lake / Beach nav cards with editorial mockups
//   6. TopTenShelf      — Top 10 deals right now
//   7. PriceDropsShelf  — Price drops + ↘ N cuts pill
//   8. NewThisWeekShelf — New this week + ✦ N added pill
//
// Each section is wrapped in an ErrorBoundary so a render failure in
// one shelf doesn't blank the whole page. The boundary's onError
// captures the exception via PostHog with a section tag.
//
// The Pro upsell modal trigger is preserved from the previous shell —
// it reads URL campaign params on mount and asks app.openProUpsellModal
// to decide show/no-show. Mount-only.
import React, { useEffect } from "react";
import { decideShouldShowUpsell } from "../lib/upsell-config.ts";
import { ErrorBoundary } from "../error-boundary.jsx";
import { HomepageHeader } from "./HomepageHeader.jsx";
import { HeroV2 } from "./HeroV2.jsx";
import { FeaturedDeal } from "./FeaturedDeal.jsx";
import { USPBand } from "./USPBand.jsx";
import { PickShoreline } from "./PickShoreline.jsx";
import { TopTenShelf, PriceDropsShelf, NewThisWeekShelf } from "./HomeShelf.jsx";

/**
 * @param {object} props
 * @param {object} props.app  — App state with goBrowse(...), openListing(...),
 *                              openSignup(...), go(...), locale
 */
export function NewHomePage({ app }) {
  const locale = app.locale;

  // Pro upsell modal trigger (carried over from the previous shell).
  // Mount-only so re-renders from routeParams tweaks don't re-fire
  // after the user dismisses the modal.
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="homepage-v2">
      <ErrorBoundary compact section="header">
        <HomepageHeader app={app} locale={locale} />
      </ErrorBoundary>
      <main className="homepage-v2-main">
        <ErrorBoundary compact section="hero">
          <HeroV2 app={app} locale={locale} />
        </ErrorBoundary>
        <ErrorBoundary compact section="featured">
          <FeaturedDeal app={app} locale={locale} />
        </ErrorBoundary>
        <ErrorBoundary compact section="usps">
          <USPBand locale={locale} />
        </ErrorBoundary>
        <ErrorBoundary compact section="shoreline">
          <PickShoreline app={app} locale={locale} />
        </ErrorBoundary>
        <ErrorBoundary compact section="top_10">
          <TopTenShelf app={app} locale={locale} />
        </ErrorBoundary>
        <ErrorBoundary compact section="price_drops">
          <PriceDropsShelf app={app} locale={locale} />
        </ErrorBoundary>
        <ErrorBoundary compact section="new_this_week">
          <NewThisWeekShelf app={app} locale={locale} />
        </ErrorBoundary>
      </main>
    </div>
  );
}
