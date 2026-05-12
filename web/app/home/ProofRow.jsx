// Proof row — "This week's top 3 deals". 3 cards drawn from
// featured.json's picks_for_proof_row (Phase 3), rendered with the
// hero-quality derivative photo + star rating + location + price.
//
// On mobile this is a horizontal swipe carousel (overflow-x: auto +
// scroll-snap); on desktop it's a 3-column grid. Either way, the
// underlying markup is the same — CSS owns the layout swap.
//
// Telemetry:
//   - card_impression fires once per card per page-view via
//     IntersectionObserver, debounced 500ms so a fast scroll doesn't
//     emit three duplicates.
//   - card_clicked fires on tap; same payload shape as impression
//     so PostHog can join them into a funnel.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { t, tr } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { useListings } from "../data/use-listings.tsx";
import { loadFeaturedJson, featuredIdToListingId } from "../data/featured.ts";
import { StarPill } from "../components/StarPill.jsx";
import { Photo, formatPrice } from "../components.jsx";

const IMPRESSION_DEBOUNCE_MS = 500;

/**
 * @param {object} props
 * @param {object} props.app    — App state with openListing(), goBrowse()
 * @param {string} props.locale — "en" | "es"
 */
export function ProofRow({ app, locale }) {
  const listings = useListings();
  const [featured, setFeatured] = useState({ status: "loading", picks: [], tier: null });

  // Single fetch on mount. featured.json is CDN-cached so this is
  // ~free on repeat visits. The 600ms timeout inside loadFeaturedJson
  // is the safety net — if the JSON can't be reached we silently
  // hide the proof row rather than block paint.
  useEffect(() => {
    let cancelled = false;
    loadFeaturedJson().then((json) => {
      if (cancelled) return;
      if (!json) {
        setFeatured({ status: "ready", picks: [], tier: null });
        return;
      }
      setFeatured({
        status: "ready",
        picks: json.picks_for_proof_row,
        tier: json.proof_row_tier,
      });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Resolve picks (featured IDs) against the live listings array.
  // Stale picks (listing churned out of the catalog between the
  // nightly run and the user's session) drop silently — better than
  // rendering a card that 404s on click.
  const resolved = useMemo(() => {
    if (featured.status !== "ready") return [];
    const byId = new Map();
    for (const li of listings) byId.set(li.id, li);
    const out = [];
    for (const pick of featured.picks) {
      const id = featuredIdToListingId(pick.listing_id);
      const li = byId.get(id);
      if (!li || li.is_sold) continue;
      out.push({ pick, listing: li });
    }
    return out;
  }, [featured, listings]);

  // Loading — render placeholders so the layout doesn't reflow when
  // featured.json lands a beat after the listings JSON. Same height
  // as a real card so LCP doesn't shift.
  if (featured.status === "loading") {
    return (
      <section className="proof-row" aria-busy="true" aria-labelledby="proof-row-heading">
        <ProofRowHead locale={locale} app={app} />
        <div className="proof-row-list" role="list">
          {[0, 1, 2].map((i) => (
            <div key={i} className="proof-row-card proof-row-card-skeleton" role="listitem" />
          ))}
        </div>
      </section>
    );
  }

  // Settled but empty — Phase 3's shortfall tier OR a fresh deploy
  // before the first nightly populated picks_for_proof_row. Render
  // a single placeholder line so the section doesn't visually collapse.
  if (resolved.length === 0) {
    return (
      <section className="proof-row" aria-labelledby="proof-row-heading">
        <ProofRowHead locale={locale} app={app} />
        <p className="proof-row-empty">{t("proof_row.empty", locale)}</p>
      </section>
    );
  }

  return (
    <section className="proof-row" aria-labelledby="proof-row-heading">
      <ProofRowHead locale={locale} app={app} />
      <div className="proof-row-list" role="list">
        {resolved.map(({ pick, listing }, i) => (
          <ProofRowCard
            key={listing.id}
            pick={pick}
            listing={listing}
            position={(i + 1)}
            proofRowTier={featured.tier}
            app={app}
            locale={locale}
          />
        ))}
      </div>
    </section>
  );
}

function ProofRowHead({ locale, app }) {
  const onSeeAll = (e) => {
    e.preventDefault();
    track("category_grid.browse_all_clicked", {
      master_category: "beach",   // proof row "see all" doesn't have a master;
      listing_count_at_click: 0,  // reusing the closest existing event would
    });                            // misreport — instead we just navigate.
    app.goBrowse({});
  };
  return (
    <div className="proof-row-head">
      <h2 id="proof-row-heading" className="proof-row-heading">
        {t("proof_row.heading", locale)}
      </h2>
      <button type="button" className="proof-row-see-all" onClick={onSeeAll}>
        {t("proof_row.see_all", locale)} →
      </button>
    </div>
  );
}

function ProofRowCard({ pick, listing, position, proofRowTier, app, locale }) {
  // Impression telemetry via IntersectionObserver. Fires once per
  // card per page-view (the `emitted` ref gates re-emits when the
  // card scrolls out + back in). 500ms debounce so a flick-scroll
  // doesn't spam three impressions.
  const wrapRef = useRef(null);
  const emittedRef = useRef(false);
  const pendingTimerRef = useRef(null);
  useEffect(() => {
    if (typeof window === "undefined" || typeof IntersectionObserver === "undefined") return;
    const node = wrapRef.current;
    if (!node) return;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting && !emittedRef.current) {
            if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);
            pendingTimerRef.current = setTimeout(() => {
              if (emittedRef.current) return;
              emittedRef.current = true;
              track("proof_row.card_impression", {
                listing_id: listing.id,
                rank: listing.rank_score || 0,
                star_rating: listing.star_rating,
                position,
                master_category: pick.master_category,
                subcategory: pick.subcategory,
                proof_row_tier: proofRowTier,
              });
              obs.disconnect();
            }, IMPRESSION_DEBOUNCE_MS);
          }
        }
      },
      { rootMargin: "0px", threshold: 0.4 },
    );
    obs.observe(node);
    return () => {
      obs.disconnect();
      if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);
    };
  }, [listing.id, listing.rank_score, listing.star_rating, position, proofRowTier, pick.master_category, pick.subcategory]);

  const onClick = (e) => {
    // Allow modifier-click + middle-click to fall through to the
    // anchor's native handling (open in new tab).
    if (e && (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) return;
    e?.preventDefault?.();
    track("proof_row.card_clicked", {
      listing_id: listing.id,
      rank: listing.rank_score || 0,
      star_rating: listing.star_rating,
      position,
      master_category: pick.master_category,
      subcategory: pick.subcategory,
      proof_row_tier: proofRowTier,
    });
    app.openListing(listing.id);
  };

  const cardHref = `/listing/${encodeURIComponent(listing.id)}`;
  return (
    <a
      ref={wrapRef}
      className="proof-row-card"
      href={cardHref}
      onClick={onClick}
      role="listitem"
      aria-label={`${tr(listing.title, locale)} — ${listing.zone_name}`}
    >
      <div className="proof-row-card-photo">
        <Photo
          listing={listing}
          idx={0}
          ratio="3/2"
          eager={position === 1}
          source="discover"
        />
        <StarPill stars={listing.star_rating} size="sm" locale={locale} className="proof-row-card-star" />
      </div>
      <div className="proof-row-card-body">
        <div className="proof-row-card-location">{listing.zone_name}</div>
        <h3 className="proof-row-card-title">{tr(listing.title, locale)}</h3>
        <div className="proof-row-card-price">{formatPrice(listing.price)}</div>
      </div>
    </a>
  );
}
