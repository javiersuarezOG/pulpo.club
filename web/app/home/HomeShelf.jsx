// Homepage v2 editorial shelves — Top 10 / Price drops / New this week.
// One generic component, three instances. Each renders an editorial
// card: 100px gradient header (forest/clay/navy/gray variants), left
// + right badge in the corners, then price + meta in the white tail.
//
// Mobile (<640px): horizontal scroll, scroll-snap, cards 75% of
// viewport width, native swipe inertia, no scrollbar.
// 640-1023px: 2-column grid, first 6 visible.
// ≥1024px: 3-column grid, first 3 visible, scroll hint below.
//
// "View all →" navigates to /browse with the appropriate filter
// pre-applied (master/discovery_tag/sort). The card itself opens
// signup when clicked (until the listing-detail route is wired to
// these editorial picks).
import React, { useCallback, useEffect, useRef, useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { getCategoryImage } from "../assets/categories/index.js";

// ────────────────────────────────────────────────────────────────────
// Shared shelf scaffold

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
      // estimate position: scrollLeft / per-card width
      const firstChild = el.firstElementChild;
      const itemWidth = firstChild ? firstChild.getBoundingClientRect().width + 10 : 250;
      const pos = Math.max(0, Math.floor(el.scrollLeft / Math.max(1, itemWidth)));
      if (pos > maxReachedRef.current) maxReachedRef.current = pos;
      // Debounce-style: emit once when user has scrolled past the first card
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

function ShelfCard({ card, position, shelfKey, app }) {
  const onClick = useCallback(() => {
    try {
      track("homepage.shelf_card_clicked", {
        shelf: shelfKey,
        position,
        listing_id: card.id || `placeholder-${shelfKey}-${position}`,
      });
    } catch { /* ignore */ }
    if (app && typeof app.openSignup === "function") {
      app.openSignup({ mode: "signup" });
    }
  }, [shelfKey, position, card.id, app]);

  const imgSrc = card.image ? getCategoryImage(card.image) : null;

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
  onViewAll,
  scrollHintRemainder,
}) {
  const sectionRef = useRef(null);
  const listRef = useRef(null);
  useSectionViewed(sectionKey, sectionRef);
  useShelfScrolled(shelfKey, listRef);

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
          {cards.map((card, i) => (
            <div className="hp-shelf-list-item" role="listitem" key={i}>
              <ShelfCard card={card} position={i + 1} shelfKey={shelfKey} app={app} />
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
// Three pre-configured instances. Cards reflect the design spec's
// editorial picks. Real listings will swap in once the deal-of-the-
// week pipeline is plumbed; for now these are static editorial
// placeholders so the cold-load page is dense.

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

export function TopTenShelf({ app, locale }) {
  return (
    <HomeShelf
      app={app}
      locale={locale}
      sectionKey="top_10"
      shelfKey="top_10"
      domId="hp-shelf-top10"
      headingKey="home.shelf.top10.h2"
      cards={TOP_10_CARDS}
      scrollHintRemainder={7}
      onViewAll={() => app && app.goBrowse && app.goBrowse({})}
    />
  );
}

export function PriceDropsShelf({ app, locale }) {
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
      onViewAll={() => app && app.goBrowse && app.goBrowse({ category: "price_drop" })}
    />
  );
}

export function NewThisWeekShelf({ app, locale }) {
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
      onViewAll={() => app && app.goBrowse && app.goBrowse({ category: "new" })}
    />
  );
}
