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

export default function MapView({ results, app, onOpenListing }) {
  const lc = app?.locale || currentLocale();
  const elRef = useRef(null);
  const mapRef = useRef(null);
  const clusterRef = useRef(null);
  const onOpenRef = useRef(onOpenListing);
  const lcRef = useRef(lc);
  useEffect(() => { onOpenRef.current = onOpenListing; }, [onOpenListing]);
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
          html: `<span>${n}</span>`,
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

    mapRef.current = map;
    clusterRef.current = cluster;
    return () => {
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
      return m;
    });
    cluster.addLayers(markers);
  }, [shown]);

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
