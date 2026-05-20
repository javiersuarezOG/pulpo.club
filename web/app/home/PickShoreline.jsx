// Pick your shoreline — two large editorial cards (Lake, Beach).
// Each card has a white head (label + arrow tile + subtitle) and a
// colored mockup tail with three nested listing-row previews. The
// preview rows are decorative (aria-hidden); the whole card is a
// single button that navigates to /browse with the master filter
// applied.
import React, { useCallback, useMemo } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { IconRipple, IconBeach, IconArrowRight } from "./icons.jsx";
import { getCategoryImage } from "../assets/categories/index.js";
import { Photo } from "../components.jsx";
import { useListings } from "../data/use-listings.tsx";

// Pick a top-ranked listing whose data signals match the shoreline.
// `master_category` isn't populated for all listings yet, so derive the
// match from the existing axes: beach = beachfront_tier set OR ocean
// view; lake = has_water_body AND not beachfront. Falls through to
// master_category for any record that does have it set.
function pickShorelineHero(listings, shoreline) {
  const matches = (l) => {
    if (l.master_category === shoreline) return true;
    if (shoreline === "beach") {
      return l.beachfront_tier != null || l.has_ocean_view === true;
    }
    if (shoreline === "lake") {
      return l.has_water_body === true && l.beachfront_tier == null;
    }
    return false;
  };
  // Require a local thumbnail_url. Broker URLs (Encuentra24, Bienesonline,
  // etc.) can stall silently — no onerror, no onload — leaving the shimmer
  // skeleton visible forever. The local /photos/<id>.jpg derivative is
  // repo-served and reliable. ~91% of listings have one; falling back to
  // the category WebP is fine for the rare shoreline with zero candidates.
  return [...listings]
    .filter((l) =>
      matches(l) &&
      l.photos && l.photos.length > 0 &&
      typeof l.thumbnail_url === "string" && l.thumbnail_url.length > 0 &&
      l.rank_score != null
    )
    .sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0))[0] || null;
}

const LAKE_ROWS = [
  { price: "$324k", zone: "Lago de Coatepeque", body: "2bd cabin · -31%" },
  { price: "$198k", zone: "Lago de Suchitlán", body: "Buildable land · -26%" },
  { price: "$425k", zone: "Lago de Ilopango", body: "4bd · price drop" },
];
const BEACH_ROWS = [
  { price: "$615k", zone: "El Tunco", body: "3bd beach · -28%" },
  { price: "$845k", zone: "Las Flores", body: "Oceanfront · new today" },
  { price: "$720k", zone: "Costa del Sol", body: "3bd condo · price drop" },
];

function ShorelineCard({ shoreline, locale, app, heroListing }) {
  const isLake = shoreline === "lake";
  const labelKey = isLake ? "home.shoreline.lake.label" : "home.shoreline.beach.label";
  const rows = isLake ? LAKE_ROWS : BEACH_ROWS;

  const onClick = useCallback(() => {
    try { track("shoreline_card_clicked", { shoreline }); } catch { /* ignore */ }
    if (app && typeof app.goBrowse === "function") {
      app.goBrowse({ master_category: shoreline });
    }
  }, [shoreline, app]);

  const ariaLabel = (() => {
    const tpl = t("home.shoreline.cta_aria", locale);
    return typeof tpl === "string" ? tpl.replace("{shoreline}", t(labelKey, locale)) : t(labelKey, locale);
  })();

  // Photo: prefer the top-ranked real listing's first photo for this
  // shoreline. Falls back to the category placeholder if the catalog
  // hasn't loaded yet or no listing in this category has a photo.
  const fallbackKey = isLake ? "water_features" : "beachfront";
  const fallbackSrc = getCategoryImage(fallbackKey);

  return (
    <button
      type="button"
      className={`hp-shoreline-card hp-shoreline-card-${shoreline}`}
      onClick={onClick}
      aria-label={ariaLabel}
    >
      {heroListing ? (
        <Photo
          listing={heroListing}
          idx={0}
          ratio="auto"
          className="hp-shoreline-photo"
          eager
          thumbnail
          source="home_shoreline"
        />
      ) : fallbackSrc ? (
        <img
          src={fallbackSrc}
          alt=""
          className="hp-shoreline-photo"
          loading="eager"
          decoding="async"
          aria-hidden="true"
        />
      ) : null}
      <div className="hp-shoreline-head">
        <div className="hp-shoreline-head-left">
          <span className="hp-shoreline-icon" aria-hidden="true">
            {isLake ? <IconRipple size={16} strokeWidth={1.7} /> : <IconBeach size={16} strokeWidth={1.7} />}
          </span>
          <span className="hp-shoreline-label">{t(labelKey, locale)}</span>
        </div>
        <span className="hp-shoreline-arrow" aria-hidden="true">
          <IconArrowRight size={14} strokeWidth={1.8} />
        </span>
      </div>
      <p className="hp-shoreline-subtitle">{t("home.shoreline.subtitle", locale)}</p>
      <div className="hp-shoreline-tail" aria-hidden="true">
        {rows.map((r, i) => (
          <div className="hp-shoreline-row" key={i}>
            <span className="hp-shoreline-row-art" />
            <span className="hp-shoreline-row-text">
              <span className="hp-shoreline-row-line1">{r.price} · {r.zone}</span>
              <span className="hp-shoreline-row-line2">{r.body}</span>
            </span>
          </div>
        ))}
      </div>
    </button>
  );
}

export function PickShoreline({ app, locale }) {
  const listings = useListings();
  const lakeHero = useMemo(() => pickShorelineHero(listings, "lake"), [listings]);
  const beachHero = useMemo(() => pickShorelineHero(listings, "beach"), [listings]);

  return (
    <section className="hp-shoreline" aria-labelledby="hp-shoreline-h2">
      <div className="hp-shoreline-inner">
        <h2 id="hp-shoreline-h2" className="hp-shoreline-h2">
          {t("home.shoreline.h2", locale)}
        </h2>
        <div className="hp-shoreline-grid">
          <ShorelineCard shoreline="lake" locale={locale} app={app} heroListing={lakeHero} />
          <ShorelineCard shoreline="beach" locale={locale} app={app} heroListing={beachHero} />
        </div>
      </div>
    </section>
  );
}
