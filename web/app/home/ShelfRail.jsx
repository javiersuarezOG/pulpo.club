// Homepage shelf rail — renders each enabled shelf from
// web/app/config/shelves.ts as a section: heading + subline +
// horizontal-scroll list of cards.
//
// The legacy Shelf component in pages.jsx is heavily styled for the
// magazine theme + reads the legacy SHELVES array from data.jsx. This
// is the new-IA replacement: typed config, mobile-first carousel,
// minimum 3 cards to render (per the shelf min_items default lowered
// in Phase 1d).
//
// Per Q6 of the rewrite plan, the rewrite reduces 15 → 2 shelves:
//   - new_this_week  (first_seen_date <= 7)
//   - price_drops    (is_repriced === true)
// Both add pure activity signal that doesn't duplicate the category
// grid above.
import React, { useMemo } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { useListings } from "../data/use-listings.tsx";
import { activeShelves, SHELF_MIN_ITEMS_DEFAULT } from "../config/shelves.ts";
import { ListingCard, Icon } from "../components.jsx";

// Cards per rail above the fold. The shelf component itself does NOT
// virtualize; capping at MAX_VISIBLE keeps the DOM cost predictable
// when a shelf's filter matches the whole catalog.
const MAX_VISIBLE = 8;

/**
 * @param {object} props
 * @param {object} props.app    — App state with openListing(), goBrowse()
 * @param {string} props.locale — "en" | "es"
 */
export function ShelfRail({ app, locale }) {
  const listings = useListings();
  const shelves = activeShelves();

  // Resolve each shelf's filter ONCE per listings-change. Empty
  // shelves are dropped from the render set so the section doesn't
  // visually collapse when a filter matches nothing.
  const resolved = useMemo(() => {
    if (!listings || listings.length === 0) return [];
    const out = [];
    for (const shelf of shelves) {
      const items = [];
      for (const li of listings) {
        if (li.is_sold) continue;
        try {
          if (shelf.filter(li)) items.push(li);
          if (items.length >= MAX_VISIBLE) break;
        } catch {
          // A filter throw shouldn't kill the whole rail — log nothing
          // (telemetry covers exceptions via ErrorBoundary's catch);
          // just skip this listing.
        }
      }
      const minItems = shelf.min_items ?? SHELF_MIN_ITEMS_DEFAULT;
      if (items.length >= minItems) {
        out.push({ shelf, items });
      }
    }
    return out;
  }, [listings, shelves]);

  if (resolved.length === 0) return null;

  return (
    <section className="shelf-rail" aria-label={t("shelf_rail.aria", locale)}>
      {resolved.map(({ shelf, items }) => (
        <Shelf key={shelf.key} shelf={shelf} items={items} app={app} locale={locale} />
      ))}
    </section>
  );
}

function Shelf({ shelf, items, app, locale }) {
  const label = shelf.label[locale === "es" ? "es" : "en"];
  const subline = shelf.subline ? shelf.subline[locale === "es" ? "es" : "en"] : null;

  const onCardOpen = (listing) => {
    track("card.clicked", {
      listing_id: listing.id,
      source_view: "discover",
      source_shelf: shelf.key,
    });
    app.openListing(listing.id);
  };

  return (
    <section className="shelf-rail-section" aria-labelledby={`shelf-${shelf.key}`}>
      <header className="shelf-rail-head">
        <div className="shelf-rail-head-text">
          <h2 id={`shelf-${shelf.key}`} className="shelf-rail-title">
            <span className="shelf-rail-icon" aria-hidden="true">
              <Icon name={shelf.icon} size={20} strokeWidth={1.6} />
            </span>
            {label}
          </h2>
          {subline && <p className="shelf-rail-subline">{subline}</p>}
        </div>
      </header>
      <div className="shelf-rail-list" role="list">
        {items.map((listing, i) => (
          <div className="shelf-rail-item" role="listitem" key={listing.id}>
            <ListingCard
              listing={listing}
              app={app}
              onOpen={onCardOpen}
              source="discover"
              priority={i < 3}
            />
          </div>
        ))}
      </div>
    </section>
  );
}
