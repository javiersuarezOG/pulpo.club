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

// PRD A5 — raised 5 → 10 per the PRD's shelf-rendering threshold.
// Gated on A3 (shelf-aware photo waiver) being live: without the
// loose-eligible top-up, every shelf with 7-8 strict-eligible listings
// would disappear under the higher threshold. With A3, shelves fill to
// 10 — trailing positions render the "Foto aún no disponible"
// placeholder when the broker hasn't shared a photo yet.
const MIN_REAL_LISTINGS = 10;

// Curated shelves only surface complete listings. A listing missing
// price or area never qualifies regardless of how strong its other
// signals are — the shelf is a quality promise, not a recall surface.
function isShelfEligible(l) {
  return !l.is_incomplete && l.photos && l.photos.length > 0;
}

// PRD A3 — shelf-aware photo gate. When a shelf has < MIN_REAL_LISTINGS
// strict-eligible listings, the picker tops up with loose-eligible
// listings (no photo) so the shelf still renders at full capacity.
// Loose-eligible cards stamp `_needs_photo_placeholder=true` (FE-only,
// not persisted to the Listing type) so ShelfCard renders the
// "Foto aún no disponible" placeholder in place of <Photo>.
function isShelfEligibleLoose(l) {
  return !l.is_incomplete;
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
    // PRD A3 — shelf-aware photo waiver. When the shelf is thin and
    // we topped up with loose-eligible listings, the card carries a
    // `_needs_photo_placeholder` stamp and renders the "Foto aún no
    // disponible" placeholder in place of <Photo>. The card is still
    // clickable; only the visual differs.
    const needsPlaceholder = listing._needs_photo_placeholder === true;
    return (
      <article className="hp-shelf-card hp-shelf-card-real" onClick={onClick}>
        <div className="hp-shelf-card-art">
          {needsPlaceholder ? (
            <div
              className="hp-shelf-card-photo-placeholder"
              aria-label={t("home.shelf.photo_pending_aria", locale)}
              role="img"
            >
              <Icon name="camera" size={36} strokeWidth={1.4} aria-hidden="true" />
              <span className="hp-shelf-card-photo-placeholder-text">
                {t("home.shelf.photo_pending", locale)}
              </span>
            </div>
          ) : (
            <Photo
              listing={listing}
              idx={0}
              ratio="4/3"
              className="hp-shelf-card-img"
              eager={eager}
              source="home_shelf"
              thumbnail
            />
          )}
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

  const useReal = heroV4 && Array.isArray(listings) && listings.length >= MIN_REAL_LISTINGS;
  const items = useReal ? listings : cards;

  // hero_v4: a shelf with too few real listings is hidden entirely rather
  // than falling back to editorial cards — the user explicitly asked for
  // shelves to disappear when there's not enough real data behind them.
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
// PRD A3 — shelf-aware photo waiver. First pass picks strict-eligible
// listings (have at least one photo). If we don't have enough to fill
// the shelf, top up with loose-eligible listings (no photo) and stamp
// `_needs_photo_placeholder=true` so the card renders the placeholder
// in place of <Photo>. The placeholder card is fully clickable; only
// the visual differs.
function pickTopByMasterAndSub(listings, master, sub, n) {
  // Includes A4's agricultural defense-in-depth clause: shelf renders
  // never include is_agricultural listings even when callers bypass
  // the data hook's excludeAgricultural filter.
  const cohort = [...listings].filter(
    (l) =>
      l.master_category === master &&
      l.subcategory === sub &&
      l.rank_score != null &&
      l.is_agricultural !== true,
  );

  const strict = cohort
    .filter(isShelfEligible)
    .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0));

  if (strict.length >= n) {
    return strict.slice(0, n);
  }

  const loose = cohort
    .filter((l) => isShelfEligibleLoose(l) && !(l.photos && l.photos.length > 0))
    .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0))
    .map((l) => ({ ...l, _needs_photo_placeholder: true }));

  // Concat strict + loose; truncate to n. Strict listings always sort
  // ahead of loose ones because they already have a photo.
  return [...strict, ...loose].slice(0, n);
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
