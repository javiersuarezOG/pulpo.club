// Category grid — 2 sections × 3 tiles each (Beach × {Homes, Condos,
// Land} + Lake × same). Live listing counts read from useListings()
// so the "Browse all 412 →" link reflects current catalog state.
//
// Tile copy lives in web/app/config/ia.ts (TS mirror of
// pulpo/ia_config.py); section headings + "Browse all" template live
// in i18n.jsx. Both are bilingual at write time.
//
// Mobile-first: tiles stack 2-up × 3-rows on small screens, switch
// to 3-up × 2-rows from 768px. Each tile is a button (NOT a link)
// because the route change goes through app.goBrowse() to drive the
// SPA's pushState — but the tile carries a real <a> href for SEO +
// middle-click + cmd-click support, identical pattern to ListingCard.
import React, { useMemo } from "react";
import { t, tr } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { useListings } from "../data/use-listings.tsx";
import {
  MASTER_CATEGORIES,
  SUBCATEGORIES,
  MASTER_CATEGORY_LABELS,
  SUBCATEGORY_LABELS,
  tileCopy,
} from "../config/ia.ts";

const SECTION_ACCENT = {
  beach: "var(--accent-beach, #2f8f6f)",  // green; tokens.css owns the actual value
  lake:  "var(--accent-lake,  #2f6fa4)",  // blue
};

/**
 * Map a listing's bucket signal to a count in the current catalog.
 * Returns a 2-level object: counts[master][sub] + counts[master].total.
 */
function bucketCounts(listings) {
  const counts = {
    beach: { homes: 0, condos: 0, land: 0, total: 0 },
    lake:  { homes: 0, condos: 0, land: 0, total: 0 },
  };
  for (const li of listings) {
    if (li.is_sold) continue;
    const m = li.master_category;
    const s = li.subcategory;
    if (m !== "beach" && m !== "lake") continue;
    if (s !== "homes" && s !== "condos" && s !== "land") continue;
    counts[m][s] += 1;
    counts[m].total += 1;
  }
  return counts;
}

/**
 * @param {object} props
 * @param {object} props.app     — the App state object with goBrowse(...)
 * @param {string} props.locale  — "en" | "es"
 */
export function CategoryGrid({ app, locale }) {
  const listings = useListings();
  const counts = useMemo(() => bucketCounts(listings), [listings]);

  const onTileClick = (master, sub) => {
    track("category_grid.tile_clicked", {
      master_category: master,
      subcategory: sub,
      listing_count_at_click: counts[master][sub],
    });
    // Deep-link into Browse with the master + sub filter applied.
    // BrowsePage's mount-time effect reads these query params and
    // sets initial filter state (Phase 5 wires this end-to-end).
    app.goBrowse({ category: `${master}_${sub}`, master, sub });
  };

  const onBrowseAllClick = (master) => {
    track("category_grid.browse_all_clicked", {
      master_category: master,
      listing_count_at_click: counts[master].total,
    });
    app.goBrowse({ category: master, master });
  };

  return (
    <section className="category-grid" aria-labelledby="category-grid-heading">
      <h2 id="category-grid-heading" className="sr-only">
        {/* Combined heading for screen readers; the visible UI uses
            per-section headings below to preserve the visual split. */}
        {t("category_grid.beach_heading", locale)} · {t("category_grid.lake_heading", locale)}
      </h2>
      {MASTER_CATEGORIES.map((master) => {
        const sectionHeadingKey = `category_grid.${master}_heading`;
        const masterCount = counts[master].total;
        const browseAllLabel = t("category_grid.browse_all", locale, { n: masterCount });
        const masterLabel = tr(MASTER_CATEGORY_LABELS[master], locale).toLowerCase();
        const browseAllAria = t("category_grid.browse_all_aria", locale, {
          n: masterCount,
          master: masterLabel,
        });
        return (
          <div
            key={master}
            className={`category-grid-section category-grid-section-${master}`}
            style={{ ["--section-accent"]: SECTION_ACCENT[master] }}
          >
            <div className="category-grid-section-head">
              <h3 className="category-grid-section-heading">
                <span className="category-grid-section-dot" aria-hidden="true" />
                {t(sectionHeadingKey, locale)}
              </h3>
              <button
                type="button"
                className="category-grid-browse-all"
                onClick={() => onBrowseAllClick(master)}
                aria-label={browseAllAria}
                disabled={masterCount === 0}
              >
                {browseAllLabel}
              </button>
            </div>
            <div className="category-grid-tiles" role="list">
              {SUBCATEGORIES.map((sub) => {
                const subCount = counts[master][sub];
                const copy = tileCopy(master, sub);
                const subLabel = tr(SUBCATEGORY_LABELS[sub], locale);
                return (
                  <button
                    type="button"
                    key={sub}
                    role="listitem"
                    className="category-grid-tile"
                    onClick={() => onTileClick(master, sub)}
                    disabled={subCount === 0}
                    aria-label={`${subLabel} · ${subCount}`}
                  >
                    <div className="category-grid-tile-head">
                      <span className="category-grid-tile-title">{subLabel}</span>
                      <span className="category-grid-tile-count">{subCount}</span>
                    </div>
                    <p className="category-grid-tile-body">{tr(copy, locale)}</p>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </section>
  );
}
