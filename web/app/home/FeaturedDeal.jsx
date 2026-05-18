// Featured deal — single editorial card between hero and USPs.
// Mobile: stacked single column. ≥768px: 280px-narrative + 1fr-panel
// two-column.
//
// Wave-5b: when `featured_deal_real_v1` is on, the card resolves a
// real listing from featured.json + the local listings cache and
// renders its photo / zone / price / days_listed. Drops the
// value-estimate stat (the data model has no market-value field —
// the prior $632k figure was fabricated) and the discount pill.
//
// Flag off OR resolution-miss → byte-for-byte identical to today's
// hardcoded placeholder. The real-data variant degrades gracefully:
// if featured.json fails or the listing id doesn't resolve, we keep
// the hardcoded card so the surface never disappears mid-render.

import React, { useCallback, useEffect, useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { IconArrowRight } from "./icons.jsx";
import { getCategoryImage } from "../assets/categories/index.js";
import { Photo, formatPrice, formatDaysListed } from "../components.jsx";
import { routeCtaForState, trackCtaRouted, dispatchCentralBranch } from "../lib/cta-routing";
import { readFeatureFlag } from "../lib/feature-flag";
import { tierFor } from "../lib/gating";
import { useListings } from "../data/use-listings.tsx";
import { loadFeaturedJson, featuredIdToListingId } from "../data/featured";

export function FeaturedDeal({ app, locale }) {
  const flagEnabled = readFeatureFlag("featured_deal_real_v1", false);
  const listings = useListings();

  // Resolved real listing for the real-data variant. null until the
  // async featured.json fetch lands AND the id resolves in the local
  // listings cache. Stays null on any failure → component falls back
  // to the hardcoded card.
  const [resolved, setResolved] = useState(null);

  useEffect(() => {
    if (!flagEnabled) return;
    if (!listings || listings.length === 0) return;
    let cancelled = false;
    loadFeaturedJson().then((featured) => {
      if (cancelled) return;
      if (!featured) return;
      // pool[0] is the current pick; subsequent entries are the
      // rotation reserve. Walk the pool until we find one in the
      // local cache — first match wins.
      for (const entry of featured.pool) {
        const id = featuredIdToListingId(entry.listing_id);
        const match = listings.find((l) => l.id === id);
        if (match) { setResolved(match); return; }
      }
    }).catch(() => { /* swallow — hardcoded fallback already rendered */ });
    return () => { cancelled = true; };
  }, [flagEnabled, listings]);

  const useReal = flagEnabled && resolved !== null;

  const onClick = useCallback(() => {
    try { track("homepage.featured_deal_clicked", {}); } catch { /* ignore */ }

    // cta_routing_v2 is the older Wave-1 kill switch; this flag is
    // the source of truth for the click routing layer. Keep the
    // legacy fallback so a Wave-1 rollback doesn't leak through here.
    const routingFlag = readFeatureFlag("cta_routing_v2", true);
    if (!routingFlag) {
      if (app && typeof app.openSignup === "function") {
        app.openSignup({ mode: "signup" });
      }
      return;
    }
    const branch = routeCtaForState("featured_deal", app?.user);
    trackCtaRouted("featured_deal", app?.user, branch, true);

    if (branch === "passthrough") {
      // Wave-5b: with a resolved listing in hand, passthrough opens
      // the detail panel for signed-in tiers. Without a listing (flag
      // off or resolution miss), passthrough remains a no-op as in
      // Wave 4.
      if (useReal && app && typeof app.openListing === "function") {
        app.openListing(resolved.id);
      }
      return;
    }
    // Anon → free_signup. Carry the listing id (if we have one) so
    // the post-signin chain lands on the detail panel.
    void dispatchCentralBranch(branch, app, {
      trigger: "featured_deal",
      ...(useReal ? { pendingListing: resolved.id } : {}),
    });
  }, [app, useReal, resolved]);

  // Telemetry once per mount so dashboards can see real-vs-hardcoded
  // engagement. `user_state` mirrors the cta_routed property shape.
  useEffect(() => {
    if (!useReal) return;
    try {
      track("featured_deal_resolved", {
        listing_id: resolved.id,
        user_state: tierFor(app?.user),
      });
    } catch { /* ignore */ }
    // Fires only when the real listing first resolves.
  }, [useReal, resolved, app]);

  return (
    <section className="hp-featured" aria-labelledby="hp-featured-title">
      <article className="hp-featured-card" onClick={onClick}>
        <div className="hp-featured-left">
          <span className="hp-featured-eyebrow">{t("home.featured.eyebrow", locale)}</span>
          <h2 id="hp-featured-title" className="hp-featured-title">
            {t(useReal ? "home.featured.title_real" : "home.featured.title", locale)}
          </h2>
          <p className="hp-featured-body">
            {t(useReal ? "home.featured.body_real" : "home.featured.body", locale)}
          </p>
          <button
            type="button"
            className="hp-featured-arrow"
            onClick={(e) => { e.stopPropagation(); onClick(); }}
            aria-label={t("home.featured.cta_aria", locale)}
          >
            <IconArrowRight size={16} />
          </button>
        </div>
        <div className="hp-featured-right">
          <div className="hp-featured-panel">
            <div className="hp-featured-panel-head">
              <span className="hp-featured-zone">
                {useReal ? (resolved.zone_name || t("home.featured.zone", locale))
                         : t("home.featured.zone", locale)}
              </span>
              {!useReal && (
                <span className="hp-featured-tag">{t("home.featured.tag", locale)}</span>
              )}
            </div>
            <div className="hp-featured-art">
              {useReal ? (
                <Photo
                  listing={resolved}
                  idx={0}
                  ratio="4/3"
                  className="hp-featured-art-img"
                  eager
                  source="featured_deal"
                />
              ) : (
                <>
                  <img
                    src={getCategoryImage("water_features")}
                    alt=""
                    className="hp-featured-art-img"
                    loading="eager"
                    decoding="async"
                  />
                  <span className="hp-featured-discount">{t("home.featured.discount", locale)}</span>
                </>
              )}
            </div>
            <dl className="hp-featured-stats">
              <div className="hp-featured-stat">
                <dt>{t("home.featured.stat_asking", locale)}</dt>
                <dd>{useReal ? formatPrice(resolved.price) : "$487,000"}</dd>
              </div>
              {!useReal && (
                <div className="hp-featured-stat">
                  <dt>{t("home.featured.stat_value", locale)}</dt>
                  <dd className="hp-featured-stat-value">$632,000</dd>
                </div>
              )}
              <div className="hp-featured-stat">
                <dt>{t("home.featured.stat_days", locale)}</dt>
                <dd>{useReal ? formatDaysListed(resolved.days_listed) : "2"}</dd>
              </div>
            </dl>
          </div>
        </div>
      </article>
    </section>
  );
}
