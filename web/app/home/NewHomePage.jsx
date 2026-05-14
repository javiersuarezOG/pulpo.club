// Homepage v2 — editorial coastal-index design.
//
// Sections, top to bottom:
//   1. HeroV2           — H1 with serif-italic "ranked.", CTAs, CSS-only newsletter preview
//   2. FeaturedDeal     — single editorial card between hero and USPs
//   3. USPBand          — "For subscribers only" + 3 cards on white
//   4. PickShoreline    — Lake / Beach nav cards with editorial mockups
//   5. TopTenShelf      — Top 10 deals right now
//   6. PriceDropsShelf  — Price drops + ↘ N cuts pill
//   7. NewThisWeekShelf — New this week + ✦ N added pill
//
// Wave-3a: HomepageHeader removed — SiteHeader (mounted at the app
// level) is the single header for every route. The hero still owns the
// "Try a free month" CTA so the home page's conversion path is intact.
//
// Each section is wrapped in an ErrorBoundary so a render failure in
// one shelf doesn't blank the whole page. The boundary's onError
// captures the exception via PostHog with a section tag.
//
// The Pro upsell modal trigger is preserved from the previous shell —
// it reads URL campaign params on mount and asks app.openProUpsellModal
// to decide show/no-show. Mount-only.
import React, { useEffect, useState } from "react";
import { decideShouldShowUpsell } from "../lib/upsell-config.ts";
import { ErrorBoundary } from "../error-boundary.jsx";
import { HeroV2 } from "./HeroV2.jsx";
import { HeroV4 } from "./HeroV4.jsx";
import { FeaturedDeal } from "./FeaturedDeal.jsx";
import { USPBand } from "./USPBand.jsx";
import { PickShoreline } from "./PickShoreline.jsx";
import { TopTenShelf, PriceDropsShelf, NewThisWeekShelf } from "./HomeShelf.jsx";
import { visibleBlocksFor } from "./blockRegistry";
import { readFeatureFlag } from "../lib/feature-flag";
import { tierFor } from "../lib/gating";
import { track } from "../telemetry/hook";
import { UspPopup } from "../components/UspPopup.jsx";
import { decideArm, armPassiveTriggers } from "../lib/usp-popup-trigger";

/**
 * @param {object} props
 * @param {object} props.app  — App state with goBrowse(...), openListing(...),
 *                              openSignup(...), go(...), locale
 */
// Wave-4: id → render-fn map. Each entry must match a BlockId in
// blockRegistry.ts; if you add a block to the registry, add the
// corresponding renderer here. Wrapping happens at the call site
// (one ErrorBoundary per block).
//
// `hero` accepts an extra `heroV4` flag so the same registry slot can
// render the dark v2 hero or the new white v4 hero depending on the
// homepage flag map.
const BLOCK_COMPONENTS = {
  hero:          ({ app, locale, heroV4 }) => (
    heroV4 ? <HeroV4 app={app} locale={locale} /> : <HeroV2 app={app} locale={locale} />
  ),
  featured:      ({ app, locale }) => <FeaturedDeal app={app} locale={locale} />,
  usps:          ({ locale })      => <USPBand locale={locale} />,
  shoreline:     ({ app, locale }) => <PickShoreline app={app} locale={locale} />,
  top_10:        ({ app, locale }) => <TopTenShelf app={app} locale={locale} />,
  price_drops:   ({ app, locale }) => <PriceDropsShelf app={app} locale={locale} />,
  new_this_week: ({ app, locale }) => <NewThisWeekShelf app={app} locale={locale} />,
};

export function NewHomePage({ app }) {
  const locale = app.locale;

  // Resolve flags + block list once per mount. The registry composes
  // filters from the flag map; downstream the legacy paid_home_rendered
  // event still reports `flag_enabled` as the paid-home flag (its
  // historical meaning) so dashboards stay stable.
  const paidHomeFlag = readFeatureFlag("paid_home_variant_v1", false);
  const uspPopupFlag = readFeatureFlag("usp_popup_v1", false);
  const heroV4Flag   = readFeatureFlag("hero_v4", false);
  const blocks = visibleBlocksFor(app.user, {
    paid_home_variant_v1: paidHomeFlag,
    usp_popup_v1:         uspPopupFlag,
    hero_v4:              heroV4Flag,
  });

  // Fire `paid_home_rendered` once per mount with the resolved list.
  // Tells us in production whether the registry filter is engaging
  // (i.e. whether paid users actually see the trimmed homepage).
  useEffect(() => {
    try {
      track("paid_home_rendered", {
        user_state: tierFor(app.user),
        blocks_visible: [...blocks],
        flag_enabled: paidHomeFlag,
      });
    } catch { /* never crash a render on telemetry */ }
    // Mount-only — don't re-fire on locale flips or block-list
    // tweaks (the registry is deterministic per (user, flag) pair).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Wave-5: USP popup. The trigger module decides whether to fire
  // synchronously (url_param) or arm passive listeners (scroll /
  // timer / exit-intent). State is null when no popup; otherwise the
  // trigger label tells UspPopup which arming path won the race.
  const [uspPopupTrigger, setUspPopupTrigger] = useState(null);

  useEffect(() => {
    if (!uspPopupFlag) return;
    const decision = decideArm({ user: app.user });
    if (decision.kind === "fire_now") {
      setUspPopupTrigger(decision.trigger);
      return;
    }
    if (decision.kind !== "arm") return;
    const teardown = armPassiveTriggers((trigger) => setUspPopupTrigger(trigger));
    return teardown;
    // Mount-only — re-arming on locale/user flips would create
    // double-fires for users who change locale mid-session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pro upsell modal trigger (carried over from the previous shell).
  // Mount-only so re-renders from routeParams tweaks don't re-fire
  // after the user dismisses the modal.
  //
  // Wave-5: when `usp_popup_v1` is on, UspPopup is the upsell-modal-
  // of-record on the homepage; the legacy ProUpsellModal stays for
  // any future surface that calls openProUpsellModal directly but
  // does NOT fire from the homepage trigger logic.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!app.openProUpsellModal) return;
    if (uspPopupFlag) return;
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
    <div className={`homepage-v2${heroV4Flag ? " hero-v4" : ""}`}>
      <main className="homepage-v2-main">
        {blocks.map((blockId) => {
          const Block = BLOCK_COMPONENTS[blockId];
          return (
            <ErrorBoundary key={blockId} compact section={blockId}>
              <Block app={app} locale={locale} heroV4={heroV4Flag} />
            </ErrorBoundary>
          );
        })}
      </main>
      {uspPopupTrigger && (
        <ErrorBoundary compact section="usp_popup">
          <UspPopup
            app={app}
            trigger={uspPopupTrigger}
            onClose={() => setUspPopupTrigger(null)}
          />
        </ErrorBoundary>
      )}
    </div>
  );
}
