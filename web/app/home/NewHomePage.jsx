// Homepage v2 — editorial coastal-index design.
//
// Sections, top to bottom:
//   1. HeroV2           — H1 with serif-italic "ranked.", CTAs, CSS-only newsletter preview
//   2. FeaturedDeal     — single editorial card between hero and USPs
//   3. USPBand          — "For subscribers only" + 3 cards on white
//   4. PickShoreline    — Lake / Beach nav cards with editorial mockups
//   5–10. Six Top-10 shelves (Phase 3): Beach × terrenos / condos /
//        homes, then Lake × terrenos / condos / homes. Each renders
//        only when ≥5 listings qualify; otherwise it's hidden. The
//        NEW + PRICE-DROP signals that used to drive their own shelves
//        now ride as per-card chips (PR #421).
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
import { HeroV5 } from "./HeroV5.jsx";
import { FeaturedDeal } from "./FeaturedDeal.jsx";
import { USPBand } from "./USPBand.jsx";
import { PickShoreline } from "./PickShoreline.jsx";
import {
  TopBeachTerrenosShelf,
  TopBeachCondosShelf,
  TopBeachHomesShelf,
  TopLakeTerrenosShelf,
  TopLakeCondosShelf,
  TopLakeHomesShelf,
} from "./HomeShelf.jsx";
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
  hero_v5:       ({ app, locale }) => <HeroV5 app={app} locale={locale} />,
  featured:      ({ app, locale }) => <FeaturedDeal app={app} locale={locale} />,
  usps:          ({ app, locale }) => <USPBand app={app} locale={locale} />,
  shoreline:     ({ app, locale }) => <PickShoreline app={app} locale={locale} />,
  top_beach_terrenos: ({ app, locale, heroV4 }) => <TopBeachTerrenosShelf app={app} locale={locale} heroV4={heroV4} />,
  top_beach_condos:   ({ app, locale, heroV4 }) => <TopBeachCondosShelf   app={app} locale={locale} heroV4={heroV4} />,
  top_beach_homes:    ({ app, locale, heroV4 }) => <TopBeachHomesShelf    app={app} locale={locale} heroV4={heroV4} />,
  top_lake_terrenos:  ({ app, locale, heroV4 }) => <TopLakeTerrenosShelf  app={app} locale={locale} heroV4={heroV4} />,
  top_lake_condos:    ({ app, locale, heroV4 }) => <TopLakeCondosShelf    app={app} locale={locale} heroV4={heroV4} />,
  top_lake_homes:     ({ app, locale, heroV4 }) => <TopLakeHomesShelf     app={app} locale={locale} heroV4={heroV4} />,
};

export function NewHomePage({ app }) {
  const locale = app.locale;

  // Resolve flags + block list once per mount. The registry composes
  // filters from the flag map; downstream the legacy paid_home_rendered
  // event still reports `flag_enabled` as the paid-home flag (its
  // historical meaning) so dashboards stay stable.
  // Default-on as of the Pro-identity pass: the registry-driven block
  // trim is now the production behavior. The flag still exists so the
  // dev tweaks panel can force the legacy "everyone sees everything"
  // path if a regression surfaces, but production should never read
  // false unless someone explicitly sets it.
  const paidHomeFlag = readFeatureFlag("paid_home_variant_v1", true);
  const uspPopupFlag = readFeatureFlag("usp_popup_v1", false);
  const heroV4Flag   = readFeatureFlag("hero_v4", true);
  // Wave-6: hero_v5 is the production default as of 2026-06-01. The
  // PostHog flag still exists as a kill-switch — set `hero_v5: false`
  // on the dashboard (or pass `?ff_hero_v5=0`) to fall back to HeroV4
  // + PickShoreline if a regression surfaces.
  const heroV5Flag   = readFeatureFlag("hero_v5", true);
  const blocks = visibleBlocksFor(app.user, {
    paid_home_variant_v1: paidHomeFlag,
    usp_popup_v1:         uspPopupFlag,
    hero_v4:              heroV4Flag,
    hero_v5:              heroV5Flag,
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
    <div className={`homepage-v2${heroV4Flag ? " hero-v4" : ""}${heroV5Flag ? " hero-v5" : ""}`}>
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
