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

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { getCategoryImage } from "../assets/categories/index.js";
import { Photo, HeartButton, formatPrice, landTypeLabel, formatDaysListed, Icon, RankTrophy, CardSignalChip } from "../components.jsx";
import { useListings } from "../data/use-listings.tsx";
import { routeCtaForState, trackCtaRouted, dispatchCentralBranch } from "../lib/cta-routing";
import { readFeatureFlag } from "../lib/feature-flag";

// Per-shelf listing limits (hero_v4 on). Desktop renders all of these
// in a wrapping grid; mobile keeps a horizontal scroll-snap rail.
const REAL_LIMITS = { top_10: 10, price_drops: 10, new_this_week: 10 };

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

// Floor for the "show fewer cards, keep the shelf visible" behavior after
// the photo-placeholder top-up was removed (homepage hard rule). A shelf
// with ≥ MIN_REAL_LISTINGS photo-eligible listings renders that many real
// cards (fewer than the full 10 is fine); below it the shelf hides rather
// than show a degenerate 1-2 card carousel. Tunable — bump toward 10 to
// favor full rows, drop toward 1 to never hide.
const MIN_REAL_LISTINGS = 4;

// Curated shelves only surface complete listings WITH a suitable picture.
// HARD RULE (2026-06-08): a homepage listing must have a locally-served
// thumbnail that the pipeline judged card-suitable. `thumbnail_url != null`
// = a /photos derivative exists; `card_eligible === true` = the source met
// the 800×600 floor AND isn't a logo/placeholder (P5 forces card_eligible
// False for those). `photos.length > 0` is NOT the gate — a broker-URL
// array is not proof of a renderable, non-404, non-logo card image (the
// exact failure that put 1,037 broken heroes + 19 xitios logos on the
// homepage).
//
// Display-gate contract (plan 003, owner rule 2026-06-12): curated
// surfaces (these shelves, the featured pools, newsletter picks) DROP a
// non-card-eligible listing entirely. Inventory surfaces
// (Browse/Discover, Saved, map cards) keep the listing findable but
// swap the bad image for the bundled category fallback — they no longer
// render the source image (see web/app/lib/card-image.ts +
// the <Photo thumbnail> choke point). The old "Discovery/Browse stays
// EXEMPT" note is superseded: inventory stays visible, but the IMAGE is
// gated everywhere.
function isShelfEligible(l) {
  return (
    !l.is_incomplete &&
    l.thumbnail_url != null &&
    l.card_eligible === true
  );
}

// Top 10: rank_score-sorted, must have at least one photo.
export function pickTopRanked(listings, n) {
  return [...listings]
    .filter((l) => l.rank_score != null && isShelfEligible(l))
    .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0))
    .slice(0, n);
}

// Shelf-specific badge derived from the listing data. Returns
// `{ text, kind, side }` or null.
//
// Phase 3 + Phase 5 retired every branch this function used to handle.
// The legacy shelfKeys (top_10 / price_drops / new_this_week) were
// replaced by six type-specific shelves whose deal grade now surfaces
// via the universal DealGradeChip in the card body (PR #425, Phase 5);
// price-drop + new signals live on the CardSignalChip overlay (#421).
// Kept as a stub so existing callers don't have to thread a removal
// through their render paths — any new shelfKey simply gets no extra
// badge from this module. */
function badgeForListing(_listing, _shelfKey) {
  return null;
}

// ────────────────────────────────────────────────────────────────────
// Shelf card — accepts EITHER `listing` (real) or `card` (hardcoded).
// Real listings get a `<Photo>` + heart + computed badge + real
// price/meta. Hardcoded cards keep their static layout.

function ShelfCard({ listing, card, position, shelfKey, app, heroV4, eager, rank, locale }) {
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
    // One tag per shelf: Top 10 shows the rank chip (#1..#10) as its
    // single overlay; Price Drops shows the −$Xk badge; New Listings
    // shows the recency badge. Stacking both reads as crowded, so each
    // shelf gets exactly one identity element.
    const isTopTen = shelfKey === "top_10";
    const badge = isTopTen ? null : badgeForListing(listing, shelfKey);
    const showRank = isTopTen && rank != null;
    // HARD RULE (2026-06-08): every homepage shelf card has a suitable
    // picture (isShelfEligible gates on thumbnail_url + card_eligible), so
    // there is no placeholder branch — always render the real <Photo>.
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
            thumbnail
          />
          {showRank && (
            <span className="pulpo-rank hp-shelf-card-rank" aria-label={`Pulpo ranked ${rank}`}>
              <span className="pulpo-rank-star" aria-hidden="true">
                <RankTrophy />
              </span>
              <span className="pulpo-rank-num">{rank}</span>
            </span>
          )}
          {badge && (
            <span className={`hp-shelf-card-badge hp-shelf-card-badge-${badge.side} hp-shelf-card-badge-${badge.kind}`}>
              {badge.text}
            </span>
          )}
          <CardSignalChip listing={listing} />
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
  subcopyKey,      // Optional one-line subtitle under the h2 (objective shelf description).
  countPill,
  iconName,        // Single icon (e.g. "cat_top10") rendered inline before the h2 text.
  iconStack,       // Phase 3: array of icons rendered as a 2- or 3-glyph stack before the h2.
                   //   e.g. ["cat_top10", "cat_beachfront", "type_terreno"] for a Top 10
                   //   beach terrenos shelf. Each entry can be {name, tone?} for color
                   //   override (trophy=gold, lake=blue, beach=green, type=ink).
  cards,
  listings,        // Wave-5 polish: when present + length >= MIN_REAL_LISTINGS, replaces cards
  heroV4 = false,  // gates the new card markup
  onViewAll,
}) {
  const sectionRef = useRef(null);
  const listRef = useRef(null);
  useSectionViewed(sectionKey, sectionRef);
  useShelfScrolled(shelfKey, listRef);

  // HARD-RULE consequence (2026-06-08): with the photo-placeholder top-up
  // removed, a thin cohort yields fewer eligible listings. Per the chosen
  // behavior — "show fewer cards, keep the shelf visible" — render the real
  // listings whenever the shelf has at least MIN_REAL_LISTINGS eligible ones
  // (a thin shelf shows e.g. 4-9 cards instead of the full 10), and only
  // hide a shelf that can't even meet that small floor (a 1-2 card carousel
  // reads as broken). Post-restore most cohorts clear 10 easily; this floor
  // only bites rare sparse cohorts (e.g. lake condos).
  const useReal = heroV4 && Array.isArray(listings) && listings.length >= MIN_REAL_LISTINGS;
  const items = useReal ? listings : cards;

  const hideShelf = heroV4 && Array.isArray(listings) && listings.length < MIN_REAL_LISTINGS;

  // Carousel state for the prev/next arrows (desktop ≥768px). Track
  // whether we can scroll further in each direction so the arrows can
  // disable cleanly at the endpoints.
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const updateArrows = useCallback(() => {
    const el = listRef.current;
    if (!el) {
      setCanScrollLeft(false);
      setCanScrollRight(false);
      return;
    }
    const max = el.scrollWidth - el.clientWidth;
    setCanScrollLeft(el.scrollLeft > 4);
    setCanScrollRight(max > 4 && el.scrollLeft < max - 4);
  }, []);

  useEffect(() => {
    if (!useReal || hideShelf) return;
    const el = listRef.current;
    if (!el) return;
    updateArrows();
    el.addEventListener("scroll", updateArrows, { passive: true });
    window.addEventListener("resize", updateArrows);
    return () => {
      el.removeEventListener("scroll", updateArrows);
      window.removeEventListener("resize", updateArrows);
    };
  }, [useReal, hideShelf, items.length, updateArrows]);

  const scrollByPage = useCallback((direction) => {
    const el = listRef.current;
    if (!el) return;
    // Page = three card-slots forward so each click reveals a fresh
    // batch while still keeping a half-card peek on the trailing edge.
    const firstChild = el.firstElementChild;
    const slot = firstChild ? firstChild.getBoundingClientRect().width + 20 : 280;
    el.scrollBy({ left: direction * slot * 3, behavior: "smooth" });
  }, []);

  const onViewAllClick = useCallback(() => {
    try { track("homepage.shelf_view_all_clicked", { shelf: shelfKey }); } catch { /* ignore */ }
    if (typeof onViewAll === "function") onViewAll();
  }, [shelfKey, onViewAll]);

  if (hideShelf) return null;

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
              {iconStack && iconStack.length > 0 ? (
                <span className="hp-shelf-h2-iconstack" aria-hidden="true">
                  {iconStack.map((g, i) => {
                    const name = typeof g === "string" ? g : g.name;
                    const tone = typeof g === "string" ? null : g.tone;
                    return (
                      <Icon
                        key={`${name}-${i}`}
                        name={name}
                        size={20}
                        strokeWidth={1.6}
                        className={`hp-shelf-h2-icon hp-shelf-h2-icon-${tone || "ink"}`}
                      />
                    );
                  })}
                </span>
              ) : iconName ? (
                <Icon name={iconName} size={22} strokeWidth={1.5} className="hp-shelf-h2-icon" />
              ) : null}
              {t(headingKey, locale)}
            </h2>
            {subcopyKey ? (
              <p className="hp-shelf-sub">{t(subcopyKey, locale)}</p>
            ) : null}
          </div>
          <div className="hp-shelf-head-right">
            {useReal && (
              <div className="hp-shelf-arrows" aria-hidden="true">
                <button
                  type="button"
                  className="hp-shelf-arrow"
                  onClick={() => scrollByPage(-1)}
                  disabled={!canScrollLeft}
                  aria-label={t("home.shelf.prev", locale)}
                >
                  <Icon name="chevron_left" size={18} strokeWidth={2} />
                </button>
                <button
                  type="button"
                  className="hp-shelf-arrow"
                  onClick={() => scrollByPage(1)}
                  disabled={!canScrollRight}
                  aria-label={t("home.shelf.next", locale)}
                >
                  <Icon name="chevron_right" size={18} strokeWidth={2} />
                </button>
              </div>
            )}
            <button type="button" className="hp-shelf-view-all" onClick={onViewAllClick}>
              {t("home.shelf.view_all", locale)}
            </button>
          </div>
        </header>
        <div ref={listRef} className="hp-shelf-list" role="list">
          {items.map((item, i) => (
            <div className="hp-shelf-list-item" role="listitem" key={useReal ? item.id : i}>
              {useReal ? (
                <ShelfCard
                  listing={item}
                  position={i + 1}
                  rank={i + 1}
                  shelfKey={shelfKey}
                  app={app}
                  heroV4={heroV4}
                  eager={i < 4}
                  locale={locale}
                />
              ) : (
                <ShelfCard
                  card={item}
                  position={i + 1}
                  shelfKey={shelfKey}
                  app={app}
                  heroV4={heroV4}
                  locale={locale}
                />
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────
// Phase 3 — Six type-specific Top 10 shelves replacing the single
// Top 10 / Price Drops / New This Week trio. Each shelf is the
// best-ranked listings within one (master_category, subcategory)
// pair. A shelf only renders when ≥ MIN_REAL_LISTINGS qualify;
// otherwise the section is silently hidden (the hero_v4 hideShelf
// branch). NEW + PRICE-DROP signals migrated to per-card chips in
// PR #421 — no more dedicated shelves for those.

// Pick the best-ranked listings for a (master, sub) cohort.
// HARD RULE (2026-06-08): no photo-placeholder top-up. Only listings with
// a suitable picture (isShelfEligible) appear on the homepage. When a
// cohort has fewer than `n` eligible listings the shelf simply renders
// FEWER cards — it never backfills a "Foto aún no disponible" placeholder
// and never hides the shelf. Discovery/Browse remains exempt (full
// inventory) — this gate is homepage-only.
//
// PR A4 defense-in-depth: the cohort also excludes is_agricultural
// listings so direct-data callers that bypass the
// excludeAgricultural data hook still get the exclusion before
// listings hit a curated shelf. Enforced by the contract test at
// tests/test_agricultural_exclusion.py.
function pickTopByMasterAndSub(listings, master, sub, n) {
  const cohort = [...listings].filter(
    (l) =>
      l.master_category === master &&
      l.subcategory === sub &&
      l.rank_score != null &&
      l.is_agricultural !== true,
  );

  return cohort
    .filter(isShelfEligible)
    .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0))
    .slice(0, n);
}

// Map subcategory → its icon name. Trophy is universal; the
// master-category glyph (cat_beachfront / cat_lake) carries the
// shoreline; this carries the property type. Triple icon-stack
// renders as `trophy → master → sub`.
const SUB_ICON = {
  homes:  "type_home",
  condos: "type_condo",
  land:   "type_terreno",
};
const MASTER_ICON = {
  beach: "cat_beachfront",
  lake:  "cat_lake",
};

function ShelfTopBySubcategory({
  app,
  locale,
  heroV4,
  master,    // "beach" | "lake"
  sub,       // "homes" | "condos" | "land"
  shelfKey,  // unique slug for telemetry
  headingKey,
  subcopyKey,
  category,  // routing slug for "View all →" (e.g. "top_beach_terrenos")
}) {
  const all = useListings();
  const listings = useMemo(
    () => (heroV4 ? pickTopByMasterAndSub(all, master, sub, 10) : []),
    [all, heroV4, master, sub],
  );
  return (
    <HomeShelf
      app={app}
      locale={locale}
      sectionKey={shelfKey}
      shelfKey={shelfKey}
      domId={`hp-shelf-${shelfKey}`}
      headingKey={headingKey}
      subcopyKey={subcopyKey}
      iconStack={[
        { name: "cat_top10",     tone: "trophy" },
        { name: MASTER_ICON[master], tone: master },
        { name: SUB_ICON[sub],   tone: "ink" },
      ]}
      cards={[]}
      listings={listings}
      heroV4={heroV4}
      onViewAll={() => app && app.goBrowse && app.goBrowse({ category })}
    />
  );
}

export function TopBeachTerrenosShelf({ app, locale, heroV4 = false }) {
  return (
    <ShelfTopBySubcategory
      app={app} locale={locale} heroV4={heroV4}
      master="beach" sub="land"
      shelfKey="top_beach_terrenos"
      headingKey="home.shelf.top_beach_terrenos.h2"
      subcopyKey="home.shelf.top_beach_terrenos.sub"
      category="top_beach_terrenos"
    />
  );
}

export function TopBeachCondosShelf({ app, locale, heroV4 = false }) {
  return (
    <ShelfTopBySubcategory
      app={app} locale={locale} heroV4={heroV4}
      master="beach" sub="condos"
      shelfKey="top_beach_condos"
      headingKey="home.shelf.top_beach_condos.h2"
      subcopyKey="home.shelf.top_beach_condos.sub"
      category="top_beach_condos"
    />
  );
}

export function TopBeachHomesShelf({ app, locale, heroV4 = false }) {
  return (
    <ShelfTopBySubcategory
      app={app} locale={locale} heroV4={heroV4}
      master="beach" sub="homes"
      shelfKey="top_beach_homes"
      headingKey="home.shelf.top_beach_homes.h2"
      subcopyKey="home.shelf.top_beach_homes.sub"
      category="top_beach_homes"
    />
  );
}

export function TopLakeTerrenosShelf({ app, locale, heroV4 = false }) {
  return (
    <ShelfTopBySubcategory
      app={app} locale={locale} heroV4={heroV4}
      master="lake" sub="land"
      shelfKey="top_lake_terrenos"
      headingKey="home.shelf.top_lake_terrenos.h2"
      subcopyKey="home.shelf.top_lake_terrenos.sub"
      category="top_lake_terrenos"
    />
  );
}

export function TopLakeCondosShelf({ app, locale, heroV4 = false }) {
  return (
    <ShelfTopBySubcategory
      app={app} locale={locale} heroV4={heroV4}
      master="lake" sub="condos"
      shelfKey="top_lake_condos"
      headingKey="home.shelf.top_lake_condos.h2"
      subcopyKey="home.shelf.top_lake_condos.sub"
      category="top_lake_condos"
    />
  );
}

export function TopLakeHomesShelf({ app, locale, heroV4 = false }) {
  return (
    <ShelfTopBySubcategory
      app={app} locale={locale} heroV4={heroV4}
      master="lake" sub="homes"
      shelfKey="top_lake_homes"
      headingKey="home.shelf.top_lake_homes.h2"
      subcopyKey="home.shelf.top_lake_homes.sub"
      category="top_lake_homes"
    />
  );
}
