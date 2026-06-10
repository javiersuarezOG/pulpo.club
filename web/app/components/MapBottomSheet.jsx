// MapBottomSheet — mobile map view bottom sheet (WS4 map XP).
//
// The mobile map sheet is a compact result list, not a carousel of full
// cards. Collapsed and expanded states share the same dense rows so the
// user can scan, scroll, and open listings without the sheet swallowing
// the map.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
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

  // Accessible card pattern: the row is a non-interactive listitem; the primary
  // "open" action is a transparent button stretched over the whole row, and the
  // heart is a SIBLING button raised above it. This avoids the invalid
  // interactive-in-interactive nesting (a real <button> inside a role="button")
  // the row had before, while keeping the whole-row tap target.
  return (
    <div
      className={`map-sheet-row${highlighted ? " is-highlighted" : ""}`}
      role="listitem"
      data-listing-id={listing.id}
      onMouseEnter={() => onHover?.(listing.id)}
      onMouseLeave={() => onHover?.(null)}
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
      <div className="map-sheet-row__heart">
        <HeartButton listingId={listing.id} app={app} variant="inline" size={16} />
      </div>
      <button
        type="button"
        className="map-sheet-row__open"
        aria-label={t("map.sheet.row_aria", lc, { title, price })}
        onClick={() => onOpenListing(listing.id)}
      />
    </div>
  );
}

// Estimated row height: .map-sheet-row min-height (78px) + 1px border-top.
// Measured from the live DOM on mount and refined, so it self-corrects if the
// row design changes — the constant is only the first-paint fallback.
const ESTIMATED_ROW_H = 79;
// Rows rendered above/below the viewport so a fast flick never shows blanks.
const OVERSCAN = 6;

export default function MapBottomSheet({ listings, app, lc, onOpenListing, onHover, hoveredId }) {
  const [expanded, setExpanded] = useState(false);
  const dragRef = useRef({ startY: 0, dragging: false, moved: false });

  // Virtualization — the mobile sheet must NOT mount all ~1,400 listings (that
  // measured ~54k DOM nodes / ~93MB heap at 375px). Window the rows by the
  // scroll position so only the visible slice (+overscan) is in the DOM; top/
  // bottom spacers preserve the real scroll height so the scrollbar is honest.
  const scrollRef = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [rowH, setRowH] = useState(ESTIMATED_ROW_H);
  const rafRef = useRef(0);

  // Measure the scroll viewport + a real row height. Re-runs when the sheet
  // expands/collapses (height changes 188px ↔ 62dvh) or the result set changes.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    setViewportH(el.clientHeight);
    const firstRow = el.querySelector(".map-sheet-row");
    if (firstRow) {
      const h = firstRow.getBoundingClientRect().height;
      if (h > 0) setRowH(h);
    }
  }, [expanded, listings.length]);

  // rAF-throttle scroll → at most one window recompute per frame.
  useEffect(() => () => cancelAnimationFrame(rafRef.current), []);
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => setScrollTop(el.scrollTop));
  };

  const total = listings.length;
  const vh = viewportH || 188; // collapsed height fallback before first measure
  const start = Math.max(0, Math.floor(scrollTop / rowH) - OVERSCAN);
  const windowCount = Math.ceil(vh / rowH) + OVERSCAN * 2;
  const end = Math.min(total, start + windowCount);
  const windowed = listings.slice(start, end);
  const padTop = start * rowH;
  const padBottom = Math.max(0, (total - end) * rowH);

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
      <div
        className="map-sheet__cards"
        ref={scrollRef}
        onScroll={onScroll}
        role="list"
        aria-label={t("map.sheet.results_aria", lc)}
      >
        {padTop > 0 && <div aria-hidden="true" style={{ height: padTop, flexShrink: 0 }} />}
        {windowed.map((listing) => (
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
        {padBottom > 0 && <div aria-hidden="true" style={{ height: padBottom, flexShrink: 0 }} />}
      </div>
    </div>
  );
}
