// Homepage v2 editorial shelves — Top 10 / Price drops / New this week.
// One generic component, three instances.
//
// Mobile (<640px): horizontal scroll, scroll-snap, cards 75% of
// viewport width, native swipe inertia, no scrollbar.
// 640-1023px: 2-column grid, first 6 visible.
// ≥1024px: 3-column grid, first 3 visible, scroll hint below.
//
// "View all →" navigates to /browse with the appropriate filter
// pre-applied (master/discovery_tag/sort).
//
// Wave-5 polish: when `hero_v4` flag is on, each shelf picks 3 real
// listings from useListings() by shelf-specific criterion and renders
// the card as photo + zone + price + days. Click → app.openListing
// (real target now). Anon click chains to free_signup with
// pendingListing. If the catalog can't yield enough real listings for
// a shelf (small dataset / strict filter), the shelf falls back to
// the hardcoded editorial cards so the surface never goes empty.

import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { getCategoryImage } from "../assets/categories/index.js";
import { Photo, HeartButton, formatPrice, landTypeLabel, formatDaysListed } from "../components.jsx";
import { useListings } from "../data/use-listings.tsx";
import { routeCtaForState, trackCtaRouted, dispatchCentralBranch } from "../lib/cta-routing";
import { readFeatureFlag } from "../lib/feature-flag";

// ────────────────────────────────────────────────────────────────────
// Shared shelf scaffold (telemetry, viewport observers — unchanged)

function useSectionViewed(sectionKey, ref) {
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const el = ref.current;
    if (!el) return;
    let fired = false;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !fired) {
            fired = true;
            try { track("homepage.section_viewed", { section: sectionKey }); } catch { /* ignore */ }
            obs.disconnect();
            return;
          }
        }
      },
      { threshold: 0.5 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [sectionKey, ref]);
}

function useShelfScrolled(shelfKey, listRef) {
  const maxReachedRef = useRef(0);
  const emittedRef = useRef(false);
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => {
      const firstChild = el.firstElementChild;
      const itemWidth = firstChild ? firstChild.getBoundingClientRect().width + 10 : 250;
      const pos = Math.max(0, Math.floor(el.scrollLeft / Math.max(1, itemWidth)));
      if (pos > maxReachedRef.current) maxReachedRef.current = pos;
      if (!emittedRef.current && maxReachedRef.current >= 1) {
        emittedRef.current = true;
        try {
          track("homepage.shelf_scrolled", {
            shelf: shelfKey,
            max_position_reached: maxReachedRef.current,
          });
        } catch { /* ignore */ }
      }
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [shelfKey, listRef]);
}

// ────────────────────────────────────────────────────────────────────
// Real-listing pickers — Wave 5 polish

const MIN_REAL_LISTINGS = 3;

// Top 10: rank_score-sorted, must have at least one photo.
function pickTopRanked(listings, n) {
  return [...listings]
    .filter((l) => l.rank_score != null && l.photos && l.photos.length > 0)
    .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0))
    .slice(0, n);
}

// Price drops: previous_price > price, sorted by % drop desc.
function pickPriceDrops(listings, n) {
  return [...listings]
    .filter((l) => l.previous_price && l.price && l.previous_price > l.price && l.photos && l.photos.length > 0)
    .map((l) => ({ l, dropPct: 1 - l.price / l.previous_price }))
    .sort((a, b) => b.dropPct - a.dropPct)
    .slice(0, n)
    .map((x) => x.l);
}

// New this week: days_listed ≤ 7, sorted by first_seen_date asc (most recent).
function pickNewThisWeek(listings, n) {
  return [...listings]
    .filter((l) => (l.days_listed ?? l.first_seen_date) <= 7 && l.photos && l.photos.length > 0)
    .sort((a, b) => (a.first_seen_date ?? 999) - (b.first_seen_date ?? 999))
    .slice(0, n);
}

// Shelf-specific badge derived from the listing data. Returns
// `{ text, kind, side }` or null. `kind` mirrors the existing
// hp-shelf-card-badge-{kind} classes; `side` is "left" or "right".
function badgeForListing(listing, shelfKey) {
  if (shelfKey === "top_10") {
    const rank = listing.rank_score ?? 0;
    if (rank >= 85) return { text: "A+ deal", kind: "dark", side: "left" };
    if (rank >= 75) return { text: "A deal", kind: "dark", side: "left" };
    if (rank >= 65) return { text: "B+ deal", kind: "dark", side: "left" };
    return null;
  }
  if (shelfKey === "price_drops" && listing.previous_price && listing.price) {
    const dollarsOff = Math.round((listing.previous_price - listing.price) / 1000);
    if (dollarsOff <= 0) return null;
    return { text: `−$${dollarsOff}k`, kind: "burgundy", side: "left" };
  }
  if (shelfKey === "new_this_week") {
    const d = listing.days_listed ?? listing.first_seen_date ?? 0;
    if (d === 0) return { text: "today", kind: "forest-cream", side: "right" };
    return { text: `${d} day${d === 1 ? "" : "s"} ago`, kind: "forest-cream", side: "right" };
  }
  return null;
}

// ────────────────────────────────────────────────────────────────────
// Shelf card — accepts EITHER `listing` (real) or `card` (hardcoded).
// Real listings get a `<Photo>` + heart + computed badge + real
// price/meta. Hardcoded cards keep their static layout.

function ShelfCard({ listing, card, position, shelfKey, app, heroV4, eager }) {
  const isReal = !!listing;
  const id = isReal ? listing.id : (card?.id || `placeholder-${shelfKey}-${position}`);

  const onClick = useCallback(() => {
    try {
      track("homepage.shelf_card_clicked", {
        shelf: shelfKey,
        position,
        listing_id: id,
      });
    } catch { /* ignore */ }

    const flagEnabled = readFeatureFlag("cta_routing_v2", true);
    if (!flagEnabled) {
      if (app && typeof app.openSignup === "function") {
        app.openSignup({ mode: "signup" });
      }
      return;
    }
    const branch = routeCtaForState("shelf_card", app?.user);
    trackCtaRouted("shelf_card", app?.user, branch, true);
    if (branch === "passthrough") {
      // Wave-5 polish: real listings now have a destination; hardcoded
      // cards still no-op (no listing to open).
      if (isReal && app && typeof app.openListing === "function") {
        app.openListing(listing.id);
      }
      return;
    }
    // Post-#262: anon + free shelf clicks resolve to free_month_modal
    // (conversion-modal funnel). The dispatcher ignores listing context
    // for that branch — funnel attribution uses `trigger: "shelf_card"`.
    void dispatchCentralBranch(branch, app, { trigger: "shelf_card" });
  }, [shelfKey, position, id, isReal, listing, app]);

  // Real-listing rendering path
  if (isReal && heroV4) {
    const badge = badgeForListing(listing, shelfKey);
    return (
      <article className="hp-shelf-card hp-shelf-card-real" onClick={onClick}>
        <div className="hp-shelf-card-art">
          <Photo
            listing={listing}
            idx={0}
            ratio="4/3"
            className="hp-shelf-card-img"
            eager={eager}
            source="home_shelf"
          />
          {badge && (
            <span className={`hp-shelf-card-badge hp-shelf-card-badge-${badge.side} hp-shelf-card-badge-${badge.kind}`}>
              {badge.text}
            </span>
          )}
          <HeartButton listingId={listing.id} app={app} variant="overlay" size={16} />
        </div>
        <div className="hp-shelf-card-body">
          <div className="hp-shelf-card-title">{listing.zone_name}</div>
          <div className="hp-shelf-card-meta">
            {landTypeLabel(listing.land_type)}
            {listing.days_listed != null && ` · ${formatDaysListed(listing.days_listed) || ""}`}
          </div>
          <div className="hp-shelf-card-price-row">
            <span className="hp-shelf-card-price">{formatPrice(listing.price)}</span>
            {listing.previous_price && listing.previous_price > listing.price && (
              <span className="hp-shelf-card-price-was">{formatPrice(listing.previous_price)}</span>
            )}
          </div>
        </div>
      </article>
    );
  }

  // Hardcoded editorial fallback (flag off, or real listings unavailable)
  const imgSrc = card?.image ? getCategoryImage(card.image) : null;
  return (
    <article className="hp-shelf-card" onClick={onClick}>
      <div className={`hp-shelf-card-art ${imgSrc ? "" : `hp-shelf-card-art-${card.gradient}`}`}>
        {imgSrc ? (
          <>
            <img
              src={imgSrc}
              alt=""
              className="hp-shelf-card-img"
              loading="eager"
              decoding="async"
            />
            <span className="hp-shelf-card-scrim" aria-hidden="true" />
          </>
        ) : null}
        {card.badgeLeft ? (
          <span className={`hp-shelf-card-badge hp-shelf-card-badge-left hp-shelf-card-badge-${card.badgeLeftKind || "dark"}`}>
            {card.badgeLeft}
          </span>
        ) : null}
        {card.badgeRight ? (
          <span className={`hp-shelf-card-badge hp-shelf-card-badge-right hp-shelf-card-badge-${card.badgeRightKind || "light"}`}>
            {card.badgeRight}
          </span>
        ) : null}
      </div>
      <div className="hp-shelf-card-body">
        <div className="hp-shelf-card-price-row">
          <span className="hp-shelf-card-price">{card.price}</span>
          {card.priceWas ? <span className="hp-shelf-card-price-was">{card.priceWas}</span> : null}
        </div>
        <p className="hp-shelf-card-meta">{card.meta}</p>
      </div>
    </article>
  );
}

export function HomeShelf({
  app,
  locale,
  sectionKey,
  shelfKey,
  domId,
  headingKey,
  countPill,
  cards,
  listings,        // Wave-5 polish: when present + length >= MIN_REAL_LISTINGS, replaces cards
  heroV4 = false,  // gates the new card markup
  onViewAll,
  scrollHintRemainder,
}) {
  const sectionRef = useRef(null);
  const listRef = useRef(null);
  useSectionViewed(sectionKey, sectionRef);
  useShelfScrolled(shelfKey, listRef);

  const useReal = heroV4 && Array.isArray(listings) && listings.length >= MIN_REAL_LISTINGS;
  const items = useReal ? listings.slice(0, cards.length) : cards;

  const onViewAllClick = useCallback(() => {
    try { track("homepage.shelf_view_all_clicked", { shelf: shelfKey }); } catch { /* ignore */ }
    if (typeof onViewAll === "function") onViewAll();
  }, [shelfKey, onViewAll]);

  return (
    <section
      id={domId}
      ref={sectionRef}
      className={`hp-shelf hp-shelf-${shelfKey}`}
      aria-labelledby={`${domId}-h2`}
    >
      <div className="hp-shelf-inner">
        <header className="hp-shelf-head">
          <div className="hp-shelf-head-left">
            {countPill ? (
              <span className={`hp-shelf-pill hp-shelf-pill-${countPill.tone || "neutral"}`}>
                {countPill.text}
              </span>
            ) : null}
            <h2 id={`${domId}-h2`} className="hp-shelf-h2">
              {t(headingKey, locale)}
            </h2>
          </div>
          <button type="button" className="hp-shelf-view-all" onClick={onViewAllClick}>
            {t("home.shelf.view_all", locale)}
          </button>
        </header>
        <div ref={listRef} className="hp-shelf-list" role="list">
          {items.map((item, i) => (
            <div className="hp-shelf-list-item" role="listitem" key={useReal ? item.id : i}>
              {useReal ? (
                <ShelfCard
                  listing={item}
                  position={i + 1}
                  shelfKey={shelfKey}
                  app={app}
                  heroV4={heroV4}
                  eager={i < 3}
                />
              ) : (
                <ShelfCard
                  card={item}
                  position={i + 1}
                  shelfKey={shelfKey}
                  app={app}
                  heroV4={heroV4}
                />
              )}
            </div>
          ))}
        </div>
        {scrollHintRemainder ? (
          <p className="hp-shelf-scroll-hint" aria-hidden="true">
            {typeof t("home.shelf.scroll_hint", locale) === "string"
              ? t("home.shelf.scroll_hint", locale).replace("{n}", String(scrollHintRemainder))
              : null}
          </p>
        ) : null}
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────
// Three pre-configured instances. Hardcoded editorial cards remain as
// the flag-off / small-dataset fallback so the homepage never empties.

const TOP_10_CARDS = [
  { image: "water_features", gradient: "forest", badgeLeft: "A+ deal", badgeLeftKind: "dark", badgeRight: "−31%", badgeRightKind: "forest", price: "$324,000", meta: "Lago de Coatepeque · 2bd" },
  { image: "beachfront",     gradient: "clay",   badgeLeft: "A deal",  badgeLeftKind: "dark", badgeRight: "−28%", badgeRightKind: "forest", price: "$615,000", meta: "El Tunco · 3bd beach" },
  { image: "agricultural",   gradient: "navy",   badgeLeft: "A deal",  badgeLeftKind: "dark", badgeRight: "−26%", badgeRightKind: "forest", price: "$198,500", meta: "Lago de Suchitlán · land" },
];

const PRICE_DROPS_CARDS = [
  { image: "water_features", gradient: "forest", badgeLeft: "−$45k", badgeLeftKind: "burgundy", price: "$425,000", priceWas: "$470k", meta: "Lago de Ilopango · 4bd" },
  { image: "ocean_view",     gradient: "clay",   badgeLeft: "−$30k", badgeLeftKind: "burgundy", price: "$720,000", priceWas: "$750k", meta: "Costa del Sol · 3bd condo" },
  { image: "mountain_view",  gradient: "gray",   badgeLeft: "−$22k", badgeLeftKind: "burgundy", price: "$268,000", priceWas: "$290k", meta: "El Sunzal · 2bd cottage" },
];

const NEW_THIS_WEEK_CARDS = [
  { image: "beachfront",     gradient: "clay",   badgeRight: "today",      badgeRightKind: "forest-cream", price: "$845,000", meta: "Las Flores · oceanfront" },
  { image: "water_features", gradient: "forest", badgeRight: "2 days ago", badgeRightKind: "forest-cream", price: "$389,000", meta: "Lago de Güija · 3bd" },
  { image: "flat_buildable", gradient: "navy",   badgeRight: "5 days ago", badgeRightKind: "forest-cream", price: "$152,000", meta: "Lago de Coatepeque · lot" },
];

export function TopTenShelf({ app, locale, heroV4 = false }) {
  const all = useListings();
  const listings = useMemo(() => (heroV4 ? pickTopRanked(all, TOP_10_CARDS.length) : []), [all, heroV4]);
  return (
    <HomeShelf
      app={app}
      locale={locale}
      sectionKey="top_10"
      shelfKey="top_10"
      domId="hp-shelf-top10"
      headingKey="home.shelf.top10.h2"
      cards={TOP_10_CARDS}
      listings={listings}
      heroV4={heroV4}
      scrollHintRemainder={7}
      onViewAll={() => app && app.goBrowse && app.goBrowse({})}
    />
  );
}

export function PriceDropsShelf({ app, locale, heroV4 = false }) {
  const all = useListings();
  const listings = useMemo(() => (heroV4 ? pickPriceDrops(all, PRICE_DROPS_CARDS.length) : []), [all, heroV4]);
  const pill = t("home.shelf.dropsCount", locale);
  return (
    <HomeShelf
      app={app}
      locale={locale}
      sectionKey="price_drops"
      shelfKey="price_drops"
      domId="hp-shelf-drops"
      headingKey="home.shelf.dropsHeading"
      countPill={{ text: typeof pill === "string" ? pill.replace("{n}", "47") : "", tone: "burgundy" }}
      cards={PRICE_DROPS_CARDS}
      listings={listings}
      heroV4={heroV4}
      onViewAll={() => app && app.goBrowse && app.goBrowse({ category: "price_drop" })}
    />
  );
}

export function NewThisWeekShelf({ app, locale, heroV4 = false }) {
  const all = useListings();
  const listings = useMemo(() => (heroV4 ? pickNewThisWeek(all, NEW_THIS_WEEK_CARDS.length) : []), [all, heroV4]);
  const pill = t("home.shelf.newCount", locale);
  return (
    <HomeShelf
      app={app}
      locale={locale}
      sectionKey="new_this_week"
      shelfKey="new_this_week"
      domId="hp-shelf-new"
      headingKey="home.shelf.newHeading"
      countPill={{ text: typeof pill === "string" ? pill.replace("{n}", "1,247") : "", tone: "sage" }}
      cards={NEW_THIS_WEEK_CARDS}
      listings={listings}
      heroV4={heroV4}
      onViewAll={() => app && app.goBrowse && app.goBrowse({ category: "new" })}
    />
  );
}
