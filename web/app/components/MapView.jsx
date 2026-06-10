// MapView — /browse map view (WS4 PR-7).
//
// Leaflet + OSM raster tiles + markercluster. This module is loaded
// lazily (React.lazy from pages.jsx) so Leaflet stays out of the entry
// bundle. Pins and clusters are L.divIcon (HTML/CSS) so we never depend
// on Leaflet's default marker PNGs — sidesteps the bundler marker-icon
// issue and keeps every asset same-origin.
//
// HONESTY (see the plan's "Map data reality" section): ~97% of coords
// are zone-level estimates and 1,582 listings collapse to ~561 distinct
// points (up to 103 on one coord). So: clustering is ON at all zooms
// (coincident points can't separate by zoom) with spiderfyOnMaxZoom;
// clusters show a COUNT, never a single price; low/None-confidence pins
// are softened (no price) and hideable; a persistent "approximate"
// legend + an "X of Y mapped" count never let the map imply precision.

import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import { t } from "../i18n.jsx";
import { hasCoords, isLowConfidenceGeo, currentLocale } from "../components.jsx";
import { track } from "../telemetry/hook";

// El Salvador rough center + zoom for the initial view.
const SV_CENTER = [13.7942, -88.8965];
const SV_ZOOM = 8;
// Hard backstop only — markercluster virtualizes the DOM (it clusters
// before creating nodes), so we add EVERY mappable listing and let it
// bound what's actually rendered. This cap exists purely to catch a
// pathological set; if it ever trips we log rather than silently drop,
// because "X of Y mapped" must stay truthful. Tuned/observed in PR-8.
const MAX_MARKERS = 5000;

// "$65k" / "$1.3M" — PRD open-Q4 chose the compact form. "" when price
// is unknown (the pin renders a neutral dot instead).
function formatPinPrice(n) {
  if (n == null || !Number.isFinite(n) || n <= 0) return "";
  if (n >= 1_000_000) {
    const m = n / 1_000_000;
    return `$${m >= 10 ? Math.round(m) : m.toFixed(1)}M`;
  }
  return `$${Math.round(n / 1000)}k`;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

// Compact cluster label so a 1,200-listing cluster reads "1.2k" instead
// of overflowing the bubble. The count renders inside a centered
// `.pulpo-cluster__count` span (CSS centers it within the bubble).
function formatClusterCount(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export default function MapView({
  results, app, onOpenListing,
  // PR-9 — card↔marker sync + search-as-I-move.
  hoveredId = null, onHoverMarker, onBoundsChange,
  searchAsIMove = true, onToggleSearchAsIMove,
  // WS4 map↔search sync — parent bumps this to refit the map to the
  // current result set when the search/filters change.
  fitNonce = 0,
}) {
  const lc = app?.locale || currentLocale();
  const elRef = useRef(null);
  const mapRef = useRef(null);
  const clusterRef = useRef(null);
  const markerByIdRef = useRef(new Map());
  const onOpenRef = useRef(onOpenListing);
  const onHoverRef = useRef(onHoverMarker);
  const onBoundsRef = useRef(onBoundsChange);
  const searchAsIMoveRef = useRef(searchAsIMove);
  const moveTimerRef = useRef(null);
  const readyRef = useRef(false); // suppress the init-triggered moveend
  // Ignore programmatic-fitBounds moveends until this timestamp. A one-shot
  // boolean was wrong: an animated fitBounds emits MORE than one moveend, so a
  // single consume left later events to write a spurious ?bbox=. A time window
  // covers every moveend the animation produces.
  const suppressMoveUntilRef = useRef(0);
  const lcRef = useRef(lc);
  useEffect(() => { onOpenRef.current = onOpenListing; }, [onOpenListing]);
  useEffect(() => { onHoverRef.current = onHoverMarker; }, [onHoverMarker]);
  useEffect(() => { onBoundsRef.current = onBoundsChange; }, [onBoundsChange]);
  useEffect(() => { searchAsIMoveRef.current = searchAsIMove; }, [searchAsIMove]);
  useEffect(() => { lcRef.current = lc; }, [lc]);

  const [hideApprox, setHideApprox] = useState(false);

  const mappable = useMemo(() => (results || []).filter(hasCoords), [results]);
  const approxCount = useMemo(
    () => mappable.filter(isLowConfidenceGeo).length,
    [mappable],
  );
  const shown = useMemo(
    () => (hideApprox ? mappable.filter((l) => !isLowConfidenceGeo(l)) : mappable),
    [mappable, hideApprox],
  );
  // The refit effect reads `shown` through a ref so it can depend ONLY on
  // fitNonce — a pan changes `shown` (via bbox→mapResults) but must NOT
  // trigger a refit, or it would fight "search as I move".
  const shownRef = useRef(shown);
  useEffect(() => { shownRef.current = shown; }, [shown]);
  // Too few mappable listings to be useful → graceful unavailable state
  // rather than a near-empty map.
  const unavailable = (results?.length ?? 0) > 0 && mappable.length === 0;

  // Init the map once.
  useEffect(() => {
    if (mapRef.current || !elRef.current || unavailable) return;
    const map = L.map(elRef.current, {
      center: SV_CENTER,
      zoom: SV_ZOOM,
      scrollWheelZoom: true,
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(map);

    const cluster = L.markerClusterGroup({
      // markercluster builds DOM lazily; chunk the initial add so a
      // large set doesn't block the main thread on first paint.
      chunkedLoading: true,
      showCoverageOnHover: false,
      // Coincident points (up to 103 on one coord) can't separate by
      // zoom — keep clustering ON at all zooms and spiderfy at max zoom
      // so every stacked listing stays reachable.
      spiderfyOnMaxZoom: true,
      zoomToBoundsOnClick: true,
      // PR-8 — tuned for El Salvador zone density: a tighter radius
      // than the 80px default so adjacent-but-distinct zones don't
      // over-merge; a wider spiderfy so a 100-listing stack fans out
      // legibly.
      maxClusterRadius: 50,
      spiderfyDistanceMultiplier: 1.6,
      iconCreateFunction: (cl) => {
        const n = cl.getChildCount();
        // Size-step the bubble by count (sm/md/lg) so a 3-listing
        // cluster reads differently from a 100-listing one.
        const step = n < 10 ? "sm" : n < 100 ? "md" : "lg";
        const px = step === "sm" ? 34 : step === "md" ? 44 : 54;
        return L.divIcon({
          // Count lives in a centered span so it stays optically centred
          // in the bubble at every tier; k-formatted so big clusters fit.
          html: `<span class="pulpo-cluster__count">${formatClusterCount(n)}</span>`,
          className: `pulpo-cluster pulpo-cluster--${step}`,
          iconSize: L.point(px, px),
        });
      },
    });
    map.addLayer(cluster);

    // Delegate popup CTA clicks: tag each marker with its listing id,
    // wire the "View listing" button when the popup opens.
    map.on("popupopen", (e) => {
      const id = e.popup?._source?._pulpoId;
      const btn = e.popup.getElement()?.querySelector(".pulpo-popup__cta");
      if (btn && id) btn.addEventListener("click", () => onOpenRef.current?.(id));
      // PR-8 — selected marker state (1.15× / raised) while its popup
      // is open. Toggle a class on the pin span inside the marker icon.
      const pin = e.popup?._source?._icon?.querySelector(".pulpo-pin");
      if (pin) pin.classList.add("pulpo-pin--selected");
    });
    map.on("popupclose", (e) => {
      const pin = e.popup?._source?._icon?.querySelector(".pulpo-pin");
      if (pin) pin.classList.remove("pulpo-pin--selected");
    });

    // PR-9 — "search as I move": debounce 400ms after a pan/zoom, then
    // report the viewport bbox so the card panel + URL narrow to it.
    // Only report viewport changes the USER caused — skip the
    // programmatic moveend(s) from the initial setView.
    const readyTimer = setTimeout(() => { readyRef.current = true; }, 600);
    map.on("moveend", () => {
      // A programmatic refit (fitNonce) must not be read as a user pan — ignore
      // every moveend inside the suppress window, not just the first one.
      if (Date.now() < suppressMoveUntilRef.current) return;
      if (!searchAsIMoveRef.current || !readyRef.current) return;
      if (moveTimerRef.current) clearTimeout(moveTimerRef.current);
      moveTimerRef.current = setTimeout(() => {
        const b = map.getBounds();
        onBoundsRef.current?.({
          minLat: b.getSouth(), minLng: b.getWest(),
          maxLat: b.getNorth(), maxLng: b.getEast(),
        });
      }, 400);
    });

    mapRef.current = map;
    clusterRef.current = cluster;

    // Leaflet caches the container size at init. On mobile the map view
    // mounts into a container whose final size isn't settled yet (the
    // view toggle/layout switch, lazy mount), so without this the tiles
    // render gray/blank and panning "rocks". Recompute once on the next
    // frame, and again whenever the viewport changes (rotate/resize).
    let resizeTimer = null;
    const invalidateSoon = () => {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        map.invalidateSize();
      }, 80);
    };
    requestAnimationFrame(() => map.invalidateSize());
    const resizeObserver =
      typeof ResizeObserver !== "undefined" && elRef.current
        ? new ResizeObserver(invalidateSoon)
        : null;
    resizeObserver?.observe(elRef.current);
    const handleResize = invalidateSoon;
    window.addEventListener("resize", handleResize);
    window.addEventListener("orientationchange", handleResize);

    return () => {
      clearTimeout(readyTimer);
      if (moveTimerRef.current) clearTimeout(moveTimerRef.current);
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeObserver?.disconnect();
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("orientationchange", handleResize);
      map.remove();
      mapRef.current = null;
      clusterRef.current = null;
    };
  }, [unavailable]);

  // (Re)draw markers whenever the shown set changes.
  useEffect(() => {
    const cluster = clusterRef.current;
    if (!cluster) return;
    cluster.clearLayers();
    // Plot EVERY mappable listing (markercluster bounds the DOM). The
    // backstop only trips on a pathological set — and logs, never drops
    // silently, so the "X of Y mapped" count stays honest.
    const slice = shown.length > MAX_MARKERS ? shown.slice(0, MAX_MARKERS) : shown;
    if (shown.length > MAX_MARKERS) {
      track("map.markers_truncated", { shown: shown.length, cap: MAX_MARKERS });
    }
    const byId = new Map();
    const markers = slice.map((l) => {
      const low = isLowConfidenceGeo(l);
      const price = low ? "" : formatPinPrice(l.price);
      const cls = [
        "pulpo-pin",
        l.is_repriced ? "pulpo-pin--drop" : "",
        l.source_type === "off_market" ? "pulpo-pin--off" : "",
        low ? "pulpo-pin--approx" : "",
      ]
        .filter(Boolean)
        .join(" ");
      const icon = L.divIcon({
        className: "pulpo-pin-wrap",
        html: `<span class="${cls}">${price || "&bull;"}</span>`,
      });
      const m = L.marker([l.lat, l.lng], {
        icon,
        keyboard: true,
        alt: t("map.marker.aria", lcRef.current, { price: price || "—", zone: l.zone_name }),
      });
      m._pulpoId = l.id;
      m.bindPopup(buildPopupHtml(l, price, lcRef.current), {
        closeButton: true,
        maxWidth: 280,
        className: "pulpo-popup-wrap",
      });
      // PR-9 — hovering a marker highlights its card in the panel.
      m.on("mouseover", () => onHoverRef.current?.(l.id));
      m.on("mouseout", () => onHoverRef.current?.(null));
      byId.set(l.id, m);
      return m;
    });
    markerByIdRef.current = byId;
    cluster.addLayers(markers);
  }, [shown]);

  // WS4 map↔search sync — refit the viewport to the shown set when the
  // parent signals a search/filter change (fitNonce bump), and once on
  // mount so the map lands on the results instead of the static SV centre.
  // Reads `shown` via shownRef and depends only on [fitNonce], so a pan
  // never refits. invalidateSize first (the lazy/mobile container may not
  // be settled), and flag the move so its moveend doesn't write ?bbox=.
  useEffect(() => {
    const pts = shownRef.current.map((l) => [l.lat, l.lng]);
    if (!mapRef.current || pts.length === 0) return;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    requestAnimationFrame(() => {
      const map = mapRef.current;
      if (!map) return;
      map.invalidateSize();
      // Drop any queued user-pan bbox write so a stale debounce can't fire with
      // the post-refit bounds, then open a window that covers the animation's
      // moveend(s). 0.4s animate + buffer; instant when reduced-motion.
      if (moveTimerRef.current) { clearTimeout(moveTimerRef.current); moveTimerRef.current = null; }
      suppressMoveUntilRef.current = Date.now() + (reduced ? 250 : 750);
      map.fitBounds(L.latLngBounds(pts), {
        padding: [40, 40], maxZoom: 13, animate: !reduced, duration: 0.4,
      });
    });
  }, [fitNonce]);

  // PR-9 — reflect an externally-hovered card onto its marker (add the
  // sync highlight class to the matching pin, if it's currently in the
  // DOM — markers inside an un-expanded cluster have no element yet).
  useEffect(() => {
    const m = hoveredId ? markerByIdRef.current.get(hoveredId) : null;
    const pin = m?._icon?.querySelector(".pulpo-pin");
    if (pin) pin.classList.add("pulpo-pin--synced");
    return () => {
      if (pin) pin.classList.remove("pulpo-pin--synced");
    };
  }, [hoveredId]);

  if (unavailable) {
    return (
      <div className="map-view map-view--unavailable">
        <p>{t("map.unavailable_for_filter", lc)}</p>
      </div>
    );
  }

  return (
    <div className="map-view">
      <div className="map-view__bar">
        <span className="map-view__count">
          {t("map.mapped_count", lc, { shown: mappable.length, total: results?.length ?? 0 })}
        </span>
        <span className="map-view__legend">{t("map.approx_legend", lc)}</span>
        {onToggleSearchAsIMove && (
          <button
            type="button"
            className={`map-view__saim${searchAsIMove ? " active" : ""}`}
            aria-pressed={searchAsIMove}
            aria-label={t("map.search_as_i_move.aria", lc)}
            onClick={() => onToggleSearchAsIMove(!searchAsIMove)}
          >
            {t("map.search_as_i_move", lc)}
          </button>
        )}
        {approxCount > 0 && (
          <label className="map-view__hide-approx">
            <input
              type="checkbox"
              checked={hideApprox}
              onChange={(e) => setHideApprox(e.target.checked)}
            />
            {t("map.hide_approx", lc, { n: approxCount })}
          </label>
        )}
      </div>
      <div ref={elRef} className="map-view__canvas" role="application" aria-label={t("map.aria", lc)} />
    </div>
  );
}

function buildPopupHtml(l, price, lc) {
  const title = (l.title && (l.title[lc] || l.title.en || l.title.es)) || l.zone_name || "";
  const bits = [price, l.zone_name].filter(Boolean).map(escapeHtml).join(" · ");
  const img = l.thumbnail_url
    ? `<img class="pulpo-popup__img" src="${escapeHtml(l.thumbnail_url)}" alt="" loading="lazy"/>`
    : "";
  return `
    <div class="pulpo-popup">
      ${img}
      <div class="pulpo-popup__title">${escapeHtml(title)}</div>
      <div class="pulpo-popup__meta">${bits}</div>
      <div class="pulpo-popup__approx">${escapeHtml(t("map.popup.approx_location", lc))}</div>
      <button type="button" class="pulpo-popup__cta">${escapeHtml(t("map.popup.view_listing", lc))}</button>
    </div>`;
}
