// MapBottomSheet — mobile map view bottom sheet (WS4 map XP).
//
// The mobile map sheet is a compact result list, not a carousel of full
// cards. Collapsed and expanded states share the same dense rows so the
// user can scan, scroll, and open listings without the sheet swallowing
// the map.

import { useRef, useState } from "react";
import { t, tr } from "../i18n.jsx";
import {
  Photo,
  HeartButton,
  formatPrice,
  formatSize,
  formatPpm,
  ppmSuffix,
  landTypeLabel,
} from "../components.jsx";

function MapSheetRow({ listing, app, lc, onOpenListing, onHover, highlighted }) {
  const title = tr(listing.title, lc);
  const price = formatPrice(listing.price);
  const ppm = formatPpm(listing.price_per_m2);
  const ppmText = ppm === "—" ? null : `${ppm}${ppmSuffix()}`;
  const facts = [formatSize(listing.size_m2), ppmText].filter(Boolean);

  return (
    <article
      className={`map-sheet-row${highlighted ? " is-highlighted" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={t("map.sheet.row_aria", lc, { title, price })}
      data-listing-id={listing.id}
      onClick={() => onOpenListing(listing.id)}
      onMouseEnter={() => onHover?.(listing.id)}
      onMouseLeave={() => onHover?.(null)}
      onKeyDown={(e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        onOpenListing(listing.id);
      }}
    >
      <Photo
        listing={listing}
        thumbnail
        ratio="1/1"
        className="map-sheet-row__photo"
        source="map_sheet"
      />
      <div className="map-sheet-row__body">
        <div className="map-sheet-row__title">{title}</div>
        <div className="map-sheet-row__meta">
          <span>{listing.zone_name}</span>
          <span>{landTypeLabel(listing.land_type)}</span>
        </div>
        <div className="map-sheet-row__facts">
          <span className="map-sheet-row__price">{price}</span>
          {facts.map((fact) => (
            <span key={fact}>{fact}</span>
          ))}
        </div>
      </div>
      <div className="map-sheet-row__heart" onClick={(e) => e.stopPropagation()}>
        <HeartButton listingId={listing.id} app={app} variant="inline" size={16} />
      </div>
    </article>
  );
}

export default function MapBottomSheet({ listings, app, lc, onOpenListing, onHover, hoveredId }) {
  const [expanded, setExpanded] = useState(false);
  const dragRef = useRef({ startY: 0, dragging: false, moved: false });

  const onPointerDown = (e) => {
    dragRef.current = { startY: e.clientY, dragging: true, moved: false };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e) => {
    const d = dragRef.current;
    if (!d.dragging) return;
    const dy = e.clientY - d.startY;
    if (Math.abs(dy) > 6) d.moved = true;
    if (dy < -40) setExpanded(true);
    else if (dy > 40) setExpanded(false);
  };
  const onPointerUp = (e) => {
    const d = dragRef.current;
    if (!d.moved) setExpanded((v) => !v);
    d.dragging = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };

  return (
    <div className={`map-sheet ${expanded ? "map-sheet--expanded" : "map-sheet--collapsed"}`}>
      <button
        type="button"
        className="map-sheet__handle"
        aria-label={t("map.sheet.handle_aria", lc)}
        aria-expanded={expanded}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <span className="map-sheet__grip" aria-hidden="true" />
      </button>
      <div className="map-sheet__cards" aria-label={t("map.sheet.results_aria", lc)}>
        {listings.map((listing) => (
          <MapSheetRow
            key={listing.id}
            listing={listing}
            app={app}
            lc={lc}
            highlighted={listing.id === hoveredId}
            onHover={onHover}
            onOpenListing={onOpenListing}
          />
        ))}
      </div>
    </div>
  );
}
