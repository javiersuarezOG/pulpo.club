// MapBottomSheet — mobile map view bottom sheet (WS4 PR-10).
//
// On mobile the map is full-bleed and the result cards live in a sheet
// that slides up from the bottom: collapsed it peeks ~1.5 cards in a
// horizontal strip (signals scrollability); dragged/tapped up it expands
// to ~60vh of vertically-scrolling cards. Drag is pointer-based; under
// prefers-reduced-motion the snap is instant (CSS disables the
// transition). Desktop hides it (the split-pane card panel is shown
// instead) — see the media queries in index.css.

import { useRef, useState } from "react";
import { ListingCard } from "../components.jsx";
import { t } from "../i18n.jsx";

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
    // Snap as soon as the intent is clear (>40px), so the gesture feels
    // responsive without tracking continuous height.
    if (dy < -40) setExpanded(true);
    else if (dy > 40) setExpanded(false);
  };
  const onPointerUp = (e) => {
    const d = dragRef.current;
    // A tap (no real drag) toggles — the handle doubles as a button.
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
      <div className="map-sheet__cards">
        {listings.map((l) => (
          <ListingCard
            key={l.id}
            listing={l}
            app={app}
            compact
            source="map_sheet"
            highlighted={l.id === hoveredId}
            onHover={onHover}
            onOpen={() => onOpenListing(l.id)}
          />
        ))}
      </div>
    </div>
  );
}
