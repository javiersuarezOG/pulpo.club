// Wave 5#7+#9 (combined) hero — white, photo-led, Airbnb/Notion-fresh.
// Replaces HeroV2's dark-forest + animated leaderboard surface when the
// `hero_v4` flag is on. Layout:
//
//   ┌──────────────────────────────────────────────────────────────┐
//   │                                                              │
//   │   ┌────────────────────┐   ┌──────────────────────────┐     │
//   │   │ kicker             │   │                          │     │
//   │   │ Big H1 with        │   │   featured listing       │     │
//   │   │ "ranked." in       │   │   photo (rounded 20px)   │     │
//   │   │ serif italic       │   │                          │     │
//   │   │                    │   │                          │     │
//   │   │ subhead            │   │                          │     │
//   │   │                    │   │                          │     │
//   │   │ [ Try a free… ]    │   │                          │     │
//   │   │                    │   │                          │     │
//   │   │ live stats line    │   │                          │     │
//   │   └────────────────────┘   └──────────────────────────┘     │
//   │                                                              │
//   └──────────────────────────────────────────────────────────────┘
//
// Mobile: photo on top (rounded), card below, full-width. The card has
// no shadow on mobile — desktop only.
//
// The hero "owns" the featured listing visually, so when the flag is on
// the home block registry filters out the standalone FeaturedDeal block
// (see blockRegistry.ts). Click anywhere on the photo → opens the
// listing detail (Wave-1 routing).

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { Icon, Photo } from "../components.jsx";
import { IconArrowRight } from "./icons.jsx";
import { readLiveCounterCache, writeLiveCounterCache } from "../lib/live-counter-cache";
import {
  SOURCE_COUNT_FALLBACK,
  LISTING_COUNT_FALLBACK,
} from "./heroConfig";
import { useListings } from "../data/use-listings.tsx";
import { loadFeaturedJson, featuredIdToListingId } from "../data/featured";
import { routeCtaForState, trackCtaRouted, dispatchCentralBranch } from "../lib/cta-routing";
import { readFeatureFlag } from "../lib/feature-flag";
import { pickHeroPhoto } from "../lib/hero-photos";

function fmtCount(n, locale) {
  try {
    return new Intl.NumberFormat(locale === "es" ? "es-CR" : "en-US").format(n);
  } catch {
    return String(n);
  }
}

export function HeroV4({ app, locale }) {
  // ── Featured listing resolution (same pattern as Wave-5b FeaturedDeal) ─
  const listings = useListings();
  const [resolved, setResolved] = useState(null);
  // Fallback hero photo from the curated pool when the featured pipeline
  // hasn't resolved (cold load, fetch failure, listing absent from
  // cache). Picked once per mount.
  const fallbackPhoto = useMemo(() => pickHeroPhoto("random"), []);

  useEffect(() => {
    if (!listings || listings.length === 0) return;
    let cancelled = false;
    loadFeaturedJson().then((featured) => {
      if (cancelled || !featured) return;
      for (const entry of featured.pool) {
        const id = featuredIdToListingId(entry.listing_id);
        const match = listings.find((l) => l.id === id);
        if (match) { setResolved(match); return; }
      }
    }).catch(() => { /* fallback photo already in place */ });
    return () => { cancelled = true; };
  }, [listings]);

  // ── Live counter (real /data/last_updated.json fetch + sessionStorage cache) ─
  const initialCounter = useMemo(() => {
    const cached = readLiveCounterCache();
    return {
      total_listings: cached?.total_listings ?? LISTING_COUNT_FALLBACK,
      source_count:   cached?.source_count   ?? SOURCE_COUNT_FALLBACK,
    };
  }, []);
  const [counter, setCounter] = useState(initialCounter);

  useEffect(() => {
    let cancelled = false;
    import("../telemetry/perf").then(({ timedFetch }) =>
      timedFetch("last_updated.json", "/data/last_updated.json", {
        headers: { Accept: "application/json" },
      })
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => {
        if (cancelled || !json) return;
        const total = typeof json.total_listings === "number" ? json.total_listings : null;
        const statuses = json.source_status || {};
        const sources = Object.keys(statuses).length || null;
        if (total != null && sources != null) {
          setCounter({ total_listings: total, source_count: sources });
          writeLiveCounterCache({
            total_listings: total,
            source_count: sources,
            fetched_at: new Date().toISOString(),
          });
        }
      })
      .catch(() => { /* keep cached / fallback values */ });
    return () => { cancelled = true; };
  }, []);

  // ── Mount telemetry ────────────────────────────────────────────────
  useEffect(() => {
    try { track("hero_v4_viewed", {}); } catch { /* ignore */ }
  }, []);

  // ── CTA + photo click handlers ─────────────────────────────────────
  const onPrimaryCta = useCallback(() => {
    const ctaText = t("home.hero.cta_primary", locale);
    try {
      track("homepage.cta_clicked", { location: "hero_primary", cta_text: ctaText });
    } catch { /* ignore */ }
    const flagEnabled = readFeatureFlag("cta_routing_v2", true);
    if (!flagEnabled) {
      if (app && typeof app.openSignup === "function") {
        app.openSignup({ mode: "signup" });
      }
      return;
    }
    const branch = routeCtaForState("hero_primary", app?.user);
    trackCtaRouted("hero_primary", app?.user, branch, true);
    if (branch === "passthrough") return;
    void dispatchCentralBranch(branch, app);
  }, [app, locale]);

  const onPhotoClick = useCallback(() => {
    if (!resolved) return;
    try {
      track("homepage.featured_deal_clicked", {});
    } catch { /* ignore */ }
    const flagEnabled = readFeatureFlag("cta_routing_v2", true);
    if (!flagEnabled) {
      if (app && typeof app.openSignup === "function") {
        app.openSignup({ mode: "signup", pendingListing: resolved.id });
      }
      return;
    }
    const branch = routeCtaForState("featured_deal", app?.user);
    trackCtaRouted("featured_deal", app?.user, branch, true);
    if (branch === "passthrough") {
      if (app && typeof app.openListing === "function") {
        app.openListing(resolved.id);
      }
      return;
    }
    void dispatchCentralBranch(branch, app, { pendingListing: resolved.id });
  }, [app, resolved]);

  const counterLine = t("home.hero.counter_template", locale, {
    count: fmtCount(counter.total_listings, locale),
    sources: counter.source_count,
  });

  return (
    <section className="hp-hero-v4" aria-labelledby="hp-hero-v4-h1">
      <div className="hp-hero-v4-inner">
        <div className="hp-hero-v4-card">
          <span className="hp-hero-v4-kicker">{t("home.hero.v4.kicker", locale)}</span>
          <h1 id="hp-hero-v4-h1" className="hp-hero-v4-h1">
            <span className="hp-hero-v4-h1-line">{t("home.hero.h1.before", locale)}</span>
            {" "}
            <span className="hp-hero-v4-h1-italic">{t("home.hero.h1.italic", locale)}</span>
          </h1>
          <p className="hp-hero-v4-subhead">{t("home.hero.v4.subhead", locale)}</p>
          <button
            type="button"
            className="hp-hero-v4-cta"
            onClick={onPrimaryCta}
          >
            <span>{t("home.hero.cta_primary", locale)}</span>
            <IconArrowRight size={16} />
          </button>
          <p className="hp-hero-v4-microcopy">{t("home.hero.microcopy", locale)}</p>
          <div className="hp-hero-v4-live" aria-label={t("home.hero.counter_live", locale)}>
            <span className="hp-hero-v4-live-dot" aria-hidden="true" />
            <span>{counterLine}</span>
          </div>
        </div>
        <div
          className={`hp-hero-v4-photo${resolved ? " hp-hero-v4-photo-clickable" : ""}`}
          onClick={resolved ? onPhotoClick : undefined}
          role={resolved ? "button" : undefined}
          tabIndex={resolved ? 0 : undefined}
          onKeyDown={resolved ? (e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onPhotoClick();
            }
          } : undefined}
          aria-label={resolved ? t("home.hero.v4.photo_aria", locale, {
            name: resolved.zone_name || t("home.featured.zone", locale),
          }) : undefined}
        >
          {resolved ? (
            <Photo
              listing={resolved}
              idx={0}
              ratio="4/3"
              className="hp-hero-v4-photo-img"
              eager
              source="hero_v4"
            />
          ) : (
            <img
              src={fallbackPhoto.url}
              alt=""
              className="hp-hero-v4-photo-img"
              loading="eager"
              decoding="async"
            />
          )}
          {resolved && (
            <span className="hp-hero-v4-photo-pill">
              <Icon name="star" size={12} strokeWidth={1.6} />
              {t("home.hero.v4.featured_pill", locale)}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
