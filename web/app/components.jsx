// Shared atoms + listing components for Pulpo
import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { t, tr, formatPriceI18n, formatSizeI18n, formatDaysListedI18n, M2_PER_VARA2 } from "./i18n.jsx";
import { track } from "./telemetry/hook";
import { uspsVisibleFor } from "./lib/gating.ts";
import { categoryImageForListing } from "./assets/categories";
import { readFeatureFlag } from "./lib/feature-flag";
import { buildSrcSet } from "./lib/img-url";

// ===== Formatters =====
// Locale-aware wrappers — pull current locale from <html lang> so plain helpers work.
function currentLocale() {
  return document.documentElement.lang || "en";
}
// PR-4c — units preference (m² vs. Salvadoran vrs²). Mirrors the locale
// pattern: stored on <html data-units>, read here so format helpers
// don't need prop-threading.
function currentUnits() {
  return document.documentElement.dataset.units === "vrs2" ? "vrs2" : "m2";
}
// `null` on price / size means the broker didn't share it. Render the
// localized "Not shared" string instead of a bare em-dash so users know
// the data gap exists at the source rather than as a render bug.
// Incomplete listings are hidden from Discover shelves + the default
// Browse view; users only see this copy after opting in via the chip,
// or via a direct link to the detail page.
function formatPrice(n) {
  if (n == null) return t("value.notshared.short", currentLocale());
  return formatPriceI18n(n, currentLocale());
}
function formatSize(m2) {
  if (m2 == null) return t("value.notshared.short", currentLocale());
  return formatSizeI18n(m2, currentLocale(), currentUnits());
}
function formatDaysListed(d) {
  if (d == null) return null;
  return formatDaysListedI18n(d, currentLocale());
}
// Null-safe price-per-square-meter. Real listings can have null
// price_per_m2 (price missing from scrape, area_m2 missing). The
// legacy index.js fmtPPM handled this — restored here as a guardrail
// against the kind of crash we hit on /preview twice.
//
// PR-4c — when the user picks vrs² in the FilterPanel, swap the
// denominator to vara² (1 vr² ≈ 0.698896 m²), so price_per_vara² =
// price_per_m² × 0.698896. Suffix swaps to /vr².
function formatPpm(n) {
  if (n == null || !Number.isFinite(n) || n <= 0) return "—";
  const lc = currentLocale();
  const isVrs = currentUnits() === "vrs2";
  const value = isVrs ? n * M2_PER_VARA2 : n;
  return `$${Math.round(value).toLocaleString(lc === "es" ? "es-CR" : "en-US")}`;
}
// Suffix to append after a formatPpm() string. Lets call sites stay
// declarative ("$X/m²" vs "$X/vr²") without each one re-checking units.
function ppmSuffix() {
  return currentUnits() === "vrs2" ? "/vr²" : "/m²";
}
function daysListedTone(d) {
  if (d == null) return "muted";
  if (d < 30) return "muted";
  if (d < 90) return "amber";
  return "urgent";
}
function landTypeLabel(typeKey) {
  if (!typeKey) return "—";
  return t(`type.${typeKey}`, currentLocale());
}
// Format a distance pill (airport/beach/town) with precision tied to
// the listing's geocoding confidence. Returns { n, approx } where
// approx=true when the underlying lat/lng is fuzzy or absent (in which
// case the distance came from a zone-table fallback). The caller picks
// the right i18n key — the "_approx" variants prefix "ca." so users see
// the precision difference. Returns null when km is null — callers
// must skip the pill entirely.
//
// Rounding tiers:
//   high confidence (within ~2km):       no rounding, show the integer km
//   medium confidence (within municipality): round to nearest 5km, "ca."
//   low confidence / no lat/lng (zone-table fallback):
//                                        round to nearest 10km, "ca."
function formatDistanceKm(km, listing) {
  if (km == null || !Number.isFinite(km)) return null;
  const conf = listing && listing.geocoding_confidence;
  const hasLatLng = !!(listing && listing.has_lat_lng);
  if (hasLatLng && conf === "high") {
    return { n: Math.round(km), approx: false };
  }
  // Zone-table fallback (no lat/lng) is roughly the zone-centroid distance
  // — the listing could be a few km off in any direction. Treat as widest
  // rounding so users don't read precision into a centroid-derived number.
  const step = (!hasLatLng || conf === "low") ? 10 : 5;
  const rounded = Math.max(step, Math.round(km / step) * step);
  return { n: rounded, approx: true };
}

// ===== Icons (inline SVG, Lucide-style) =====
const Icon = ({ name, size = 18, className = "", strokeWidth = 1.6 }) => {
  const paths = {
    heart: <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z"/>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></>,
    home: <><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2h-4v-7h-6v7H5a2 2 0 0 1-2-2z"/></>,
    grid: <><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></>,
    list: <><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
    arrow_right: <><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></>,
    arrow_left: <><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></>,
    chevron_left: <polyline points="15 18 9 12 15 6"/>,
    chevron_right: <polyline points="9 18 15 12 9 6"/>,
    chevron_down: <polyline points="6 9 12 15 18 9"/>,
    chevron_up: <polyline points="18 15 12 9 6 15"/>,
    close: <><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></>,
    map_pin: <><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/></>,
    road: <><path d="M4 19l4-14"/><path d="M16 5l4 14"/><path d="M12 5v3"/><path d="M12 12v3"/><path d="M12 19v0"/></>,
    droplet: <path d="M12 2.5s7 7.5 7 12.5a7 7 0 1 1-14 0c0-5 7-12.5 7-12.5z"/>,
    bolt: <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>,
    leaf: <><path d="M11 20A7 7 0 0 1 4 13V4h9a7 7 0 0 1 0 14h-2"/><path d="M11 20v-9"/></>,
    sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="M5 5l1.5 1.5"/><path d="M17.5 17.5L19 19"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="M5 19l1.5-1.5"/><path d="M17.5 6.5L19 5"/></>,
    mountain: <path d="M3 20l5-9 4 6 3-4 6 7z"/>,
    wave: <path d="M2 12c2 0 2-2 5-2s3 2 5 2 3-2 5-2 3 2 5 2"/>,
    camera: <><path d="M3 7h4l2-3h6l2 3h4v13H3z"/><circle cx="12" cy="13" r="4"/></>,
    zone: <><path d="M3 6h18M3 12h18M3 18h18"/></>,
    plane: <path d="M22 16.5L13 12V5a1 1 0 0 0-2 0v7L2 16.5l.5 2 8.5-2v4l-2 1v1l3-.5 3 .5v-1l-2-1v-4l8.5 2z"/>,
    sliders: <><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></>,
    check: <polyline points="4 12 10 18 20 6"/>,
    sparkle: <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>,
    octopus: <><path d="M12 3a6 6 0 0 0-6 6v3a3 3 0 0 0 3 3"/><path d="M12 3a6 6 0 0 1 6 6v3a3 3 0 0 1-3 3"/><circle cx="9" cy="9" r=".8" fill="currentColor"/><circle cx="15" cy="9" r=".8" fill="currentColor"/><path d="M6 15c0 2-2 3-2 5"/><path d="M9 15c0 3-1 5 0 6"/><path d="M12 15v6"/><path d="M15 15c0 3 1 5 0 6"/><path d="M18 15c0 2 2 3 2 5"/></>,
    arrow_up_right: <><line x1="7" y1="17" x2="17" y2="7"/><polyline points="7 7 17 7 17 17"/></>,
    bell: <><path d="M18 16v-5a6 6 0 0 0-12 0v5l-2 2v1h16v-1l-2-2z"/><path d="M10 21a2 2 0 0 0 4 0"/></>,
    eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></>,
    bookmark: <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>,
    star: <polygon points="12 2 15 8.5 22 9.3 17 14 18.5 21 12 17.5 5.5 21 7 14 2 9.3 9 8.5"/>,
    info: <><circle cx="12" cy="12" r="10"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="12" y1="7.5" x2="12" y2="7.51"/></>,

    /* ===== Category icons (monochrome, line) ===== */
    /* Used by PillRail. Hairline (1.6) line, geometric, no fills. */
    cat_all:        <><circle cx="5" cy="5" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="12" cy="19" r="2"/><circle cx="19" cy="19" r="2"/></>,
    cat_new:        <><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/></>,
    cat_price_drop: <><path d="M5 8l7 8 7-8"/><path d="M5 14l7 8 7-8" opacity="0.5"/></>,
    cat_beachfront: <><path d="M2 18c2 0 2-1.5 5-1.5s3 1.5 5 1.5 3-1.5 5-1.5 3 1.5 5 1.5"/><path d="M2 22c2 0 2-1.5 5-1.5s3 1.5 5 1.5 3-1.5 5-1.5 3 1.5 5 1.5"/><circle cx="18" cy="6" r="3"/></>,
    cat_ocean_view: <><circle cx="19" cy="6" r="3"/><path d="M2 14c2 0 2-1.5 5-1.5s3 1.5 5 1.5 3-1.5 5-1.5 3 1.5 5 1.5"/><path d="M2 19c2 0 2-1.5 5-1.5s3 1.5 5 1.5 3-1.5 5-1.5 3 1.5 5 1.5"/></>,
    cat_build_ready:<><path d="M3 21h18"/><path d="M5 21V10l7-5 7 5v11"/><path d="M10 21v-6h4v6"/></>,
    cat_off_market: <><path d="M2 12s4-7 10-7c2 0 4 .6 5.5 1.5"/><path d="M22 12s-4 7-10 7c-2 0-4-.6-5.5-1.5"/><path d="M3 3l18 18"/></>,
    cat_flat_land:  <><path d="M2 16h20"/><path d="M2 20h20" opacity="0.5"/><path d="M6 16V8"/><path d="M11 16V6"/><path d="M16 16v-9"/></>,
    cat_water:      <><path d="M12 3s6 7 6 12a6 6 0 1 1-12 0c0-5 6-12 6-12z"/><path d="M9 14c0 2 1 3 3 3" opacity="0.6"/></>,
    /* Lake — ellipse + ripple. Distinct from cat_water (single drop) so
       Beach (waves) vs Lake (still body of water) read at a glance. */
    cat_lake:       <><ellipse cx="12" cy="15" rx="9" ry="3.5"/><path d="M5 11c2 0 2-1.5 5-1.5s3 1.5 5 1.5 3-1.5 5-1.5" opacity="0.7"/></>,
    /* Waterfront — wave with a small flag-marker on top, signaling
       "first line to the water." Works for ocean OR lake usage. */
    cat_waterfront: <><path d="M2 18c2 0 2-1.5 5-1.5s3 1.5 5 1.5 3-1.5 5-1.5 3 1.5 5 1.5"/><path d="M2 22c2 0 2-1.5 5-1.5s3 1.5 5 1.5 3-1.5 5-1.5 3 1.5 5 1.5"/><path d="M12 12V3"/><path d="M12 3l5 2-5 2"/></>,
    /* Top 10 — trophy. Universally read as "winner / top rank" without
       needing a number; the "Top 10" chip label carries the count.
       Sourced from Lucide so stroke + proportions are tuned for small
       sizes (15px in the pill rail). */
    cat_top10:      <><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/></>,
    cat_mountain:   <><path d="M2 20l6-11 4 7"/><path d="M10 20l5-9 7 9z"/><circle cx="7" cy="5" r="1.5"/></>,
    cat_under_100k: <><circle cx="12" cy="12" r="9"/><path d="M15 9c-1-1-2-1.5-3-1.5-2 0-3 1-3 2.5 0 3 6 1.5 6 4.5 0 1.5-1 2.5-3 2.5-1.5 0-2.5-.5-3.5-1.5"/><path d="M12 6v12"/></>,
    cat_agricultural:<><path d="M12 21V9"/><path d="M12 9c0-3 2-5 5-5-1 4-3 5-5 5z"/><path d="M12 13c0-3-2-5-5-5 1 4 3 5 5 5z"/><path d="M5 21h14"/></>,
    cat_commercial: <><path d="M3 21V8l6-4 6 4v13"/><path d="M15 21V12h6v9"/><path d="M3 21h18"/><path d="M7 11h.01M7 14h.01M7 17h.01M11 11h.01M11 14h.01M11 17h.01"/></>,
    cat_motivated:  <><circle cx="12" cy="13" r="8"/><path d="M12 8v5l3 2"/><path d="M9 2h6"/></>,
  };
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
      {paths[name]}
    </svg>
  );
};

// Sprite-backed trophy used by the rank chip across three hot scroll
// paths (home-shelf cards, listing cards, results table). Renders a
// <use href> reference to the symbol mounted at the app root, so the
// browser caches one rasterization of the shape instead of repainting
// 6 bezier paths per chip on every scroll frame. Color cascades via
// currentColor on the parent `.pulpo-rank-star`.
const RankTrophy = React.memo(function RankTrophy({ size = 12 }) {
  return (
    <svg width={size} height={size} aria-hidden="true" focusable="false">
      <use href="#sprite-cat-top10" />
    </svg>
  );
});

// ===== Pulpo brand mark =====
// The spiral tentacle gripping a gold catch — pulpo wrapping itself around
// the deal it found. Standalone (no wordmark) so it can be reused across
// modals, empty states, splash screens, etc. for brand continuity.
const PulpoMark = ({ size = 22, className = "" }) => (
  <svg
    width={size}
    height={size}
    viewBox="-50 -50 100 100"
    fill="none"
    aria-hidden="true"
    className={className}
  >
    <path
      d="M -38 0 C -38 -21, -21 -38, 0 -38 C 21 -38, 38 -21, 38 0 C 38 17, 24 30, 7 30 C -8 30, -18 18, -18 4 C -18 -8, -8 -18, 4 -18 C 12 -18, 18 -12, 18 -4"
      stroke="currentColor"
      strokeWidth="8.5"
      strokeLinecap="round"
      fill="none"
    />
    {/* gripper bulb at the spiral's terminus */}
    <circle cx="18" cy="-4" r="9.5" fill="currentColor" />
    {/* gold catch held inside the gripper */}
    <circle cx="18" cy="-4" r="5.5" fill="var(--gold)" />
  </svg>
);

// ===== Pulpo wordmark =====
// Mark + Inter 700 lowercase wordmark with a small gold dot inside the
// `o` — wordmark carries the same "catch" motif as the mark. `pro`
// appends the membership pill (styling in index.css → .pulpo-logo-pro).
const PulpoLogo = ({ size = 22, pro = false }) => (
  <div className="pulpo-logo" style={{ display: "flex", alignItems: "center", gap: 10 }}>
    <PulpoMark size={size} />
    <span className="pulpo-logo-wm">
      pulp<span className="pulpo-logo-o">o</span>
    </span>
    {pro && (
      // "Pro" is a shared EN/ES brand mark. The parent button already
      // carries the localized accessible name via `nav.home_pro`, so the
      // span needs no aria-label (and shouldn't have one — nesting an
      // aria-label inside a labelled button confuses screen readers).
      <span className="pulpo-logo-pro">Pro</span>
    )}
  </div>
);

// ===== Badge =====
function Badge({ listing }) {
  const lc = currentLocale();
  // Effective listing age in days. Source-of-truth is `days_listed`
  // (parsed from the original posting's mod_dt by the scraper). When
  // that's null (source date unparseable), fall back to
  // `first_seen_date` (days since Pulpo first scraped it) — but
  // that's a weaker signal: a listing scraped today could have been
  // posted on the source 10 months ago. Prior bug shipped "Nuevo"
  // badges on listings whose footer simultaneously read "Publicado
  // hace 10 meses" because we trusted first_seen_date directly.
  const effectiveAgeDays = (typeof listing.days_listed === "number")
    ? listing.days_listed
    : listing.first_seen_date;
  let kind = null;
  if (listing.is_repriced) kind = { key: "drop", label: t("badge.price_drop", lc), color: "var(--badge-drop)" };
  else if (listing.source_type === "off_market") kind = { key: "off", label: t("badge.off_market", lc), color: "var(--badge-off)" };
  else if (effectiveAgeDays <= 3) kind = { key: "new", label: t("badge.new", lc), color: "var(--badge-new)" };
  else if (listing.readiness_score >= 3) kind = { key: "ready", label: t("badge.build_ready", lc), color: "var(--badge-ready)" };
  else if (typeof listing.days_listed === "number" && listing.days_listed >= 90) kind = { key: "motivated", label: t("badge.motivated", lc), color: "var(--badge-motivated)" };
  if (!kind) return null;
  return (
    <span className="pulpo-badge" style={{ background: kind.color }}>
      {kind.label}
    </span>
  );
}

// ===== Photo with placeholder fallback =====
// PR-photo-nav-perf — accepts `eager` (loading="eager" + fetchpriority="high")
// for the currently-visible card photo, and `onLoad` so callers can measure
// click→render latency on photo-nav arrows.
//
// PR-image-priority — image-load duration is emitted as
// `perf.card_image_load` for *eager* images only. The signal we want
// is "how long did the above-the-fold images take to land" — lazy
// images defer their fetch to intersection time, so a render→onLoad
// delta there is mostly idle scroll time, not meaningful latency.
// Caller passes `source` so PostHog can split browse vs discover vs
// saved (and so we can confirm Browse-after-filter is fixed).
function Photo({
  listing, idx = 0, ratio = "16/9", className = "",
  lazy = true, eager = false, onLoad, source,
  thumbnail = false,
}) {
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);
  // Reset loaded state when the URL changes (carousel arrow click).
  // Without this, the skeleton stays hidden while the new image streams
  // in, and the user sees the OLD photo with stale "loaded" state.
  // `thumbnail` callers (cards) read the local 600×400 derivative at
  // `thumbnail_url` — fast CDN paint, no broker dependency. Gallery
  // callers (carousels) read `photos[idx]` — broker URLs at native
  // resolution. The two were combined before, which surfaced the same
  // image twice in the carousel (the thumb at slot 0 alongside the
  // broker-native version a click away).
  const url = thumbnail
    ? (listing.thumbnail_url ?? listing.photos[0] ?? null)
    : listing.photos[idx];

  // PR-perf-4 — image optimization v2 (feature-flag-gated). When the
  // `image_optimization_v2` PostHog flag is on AND the photo lives at
  // /photos/* or /photos-hires/* on our CDN (broker URLs from
  // photo_urls[] are excluded — those are served by the broker's own
  // CDN and we don't proxy them), generate a srcset that points at
  // /api/img with WebP + multi-size variants. Browser content-
  // negotiates: gets WebP at the right pixel density per viewport.
  // Falls back to the raw `url` via the <img src={url}> child when
  // the srcset can't be built (broker URL, flag off, or unsupported
  // browser — <picture> degrades gracefully to <img>).
  //
  // The default `sizes` value covers both card surfaces (~400-800px
  // wide) and the listing-detail gallery-main (~800-1600px). For more
  // precision, future call sites can pass an explicit `sizes` prop.
  const optimizationOn = readFeatureFlag("image_optimization_v2", false);
  const optimized = useMemo(() => {
    if (!optimizationOn || !url) return null;
    const webp = buildSrcSet(url);
    if (!webp) return null;
    // Both <source> tags use the same /api/img endpoint — content
    // negotiation on the server (Accept: image/webp) picks the
    // format. We still declare type="image/webp" on the first source
    // so a browser that doesn't accept WebP falls through to the
    // <img> child cleanly.
    return { webpSrcSet: webp };
  }, [url, optimizationOn]);
  const optimizedSizes = "(min-width: 768px) 800px, 100vw";
  // Stamp start-of-perceived-load on every URL change. useMemo runs
  // during render, before the browser commits the <img src>, so the
  // elapsed value covers React commit + network fetch + decode —
  // i.e. what the user actually waits for.
  const loadStart = useMemo(
    () => (typeof performance !== "undefined" ? performance.now() : 0),
    [url]
  );
  // Ref on the <img> element so the URL-change effect can check
  // `complete + naturalWidth` for browser-cache hits. Without this,
  // cached images load synchronously before React attaches onLoad,
  // setLoaded never fires, opacity stays at 0 forever, and the
  // skeleton sits over a fully decoded image. The Discover/Browse/
  // detail-panel cycle re-renders the same listings so this used to
  // happen reliably on the second visit to a section.
  const imgRef = useRef(null);
  useEffect(() => {
    setLoaded(false);
    setErrored(false);
    // queueMicrotask defers to after the <img> element mounts and the
    // browser has had a tick to honour the synchronous cache hit, so
    // `el.complete` is meaningful. Without the defer this runs during
    // the URL-change React commit when imgRef.current may still be the
    // OLD <img> element.
    queueMicrotask(() => {
      const el = imgRef.current;
      if (el && el.complete && el.naturalWidth > 0) setLoaded(true);
    });
  }, [url]);

  // Stuck-image handling — if the image neither loaded nor errored
  // after 8 s, treat it as failed and engage the category fallback.
  // Broker URLs (Encuentra24, Bienesonline) sometimes stall without
  // firing onerror/onload (slow CDN, ad-blocker, 503-without-headers),
  // which left the shimmer skeleton visible forever. Promoting stuck →
  // errored guarantees the surface always lands on a real image.
  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    const handle = setTimeout(() => {
      if (cancelled) return;
      if (loaded || errored) return;
      try {
        const el = imgRef.current;
        const wasCachedLikely = !!(el && el.complete && el.naturalWidth > 0);
        track("image.stuck", {
          url: String(url).slice(0, 200),
          listing_id: listing.id,
          idx,
          source: source || "unknown",
          is_local: String(url).startsWith("/photos/"),
          was_cached_likely: wasCachedLikely,
        });
      } catch { /* never let telemetry break the render */ }
      setErrored(true);
    }, 8000);
    return () => { cancelled = true; clearTimeout(handle); };
  }, [url, loaded, errored, listing.id, idx, source]);

  // Lazy-image telemetry. For non-eager cards we measure viewport-
  // entry → onLoad (what the user perceives when scrolling to the
  // card). Refs persist across re-renders without triggering one.
  // We disconnect the IO + clear the refs whenever url changes so a
  // carousel-arrow click doesn't trigger a stale emit against the
  // old URL.
  const wrapRef = useRef(null);
  const lazyVisibleAtRef = useRef(null);
  const lazyEmittedRef = useRef(false);
  const lazyImgLoadedRef = useRef(false);
  useEffect(() => {
    lazyVisibleAtRef.current = null;
    lazyEmittedRef.current = false;
    lazyImgLoadedRef.current = false;
    if (eager) return;
    if (typeof window === "undefined" || typeof IntersectionObserver === "undefined") return;
    const node = wrapRef.current;
    if (!node) return;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          // Stamp visible-at the first time this card enters the
          // viewport. If the image already loaded (browser pre-fetched
          // ahead of intersection — the optimal case), emit zero.
          if (lazyVisibleAtRef.current == null) {
            lazyVisibleAtRef.current = performance.now();
            if (lazyImgLoadedRef.current && source && !lazyEmittedRef.current) {
              lazyEmittedRef.current = true;
              track("perf.card_image_lazy_load", {
                listing_id: listing.id,
                idx,
                ms: 0,
                source,
              });
            }
          }
          obs.disconnect();
          break;
        }
      },
      { rootMargin: "0px", threshold: 0.01 }
    );
    obs.observe(node);
    return () => obs.disconnect();
  }, [url, eager, source, listing.id, idx]);

  if (!url || errored) {
    // Visual fallback — always an image, never a text card. Picks a
    // bundled category WebP that matches the listing's master_category
    // / land_type. See assets/categories/index.js#categoryImageForListing.
    const fallbackUrl = categoryImageForListing(listing);
    return (
      <div className={`photo-wrap photo-fallback ${className}`} style={{ aspectRatio: ratio }}>
        <img
          src={fallbackUrl}
          alt={`${tr(listing.title, currentLocale())} — ${listing.zone_name}`}
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          fetchpriority={eager ? "high" : "auto"}
        />
      </div>
    );
  }
  const imgElement = (
    <img
      ref={imgRef}
      src={url}
      alt={`${tr(listing.title, currentLocale())} — ${listing.zone_name}`}
      loading={eager ? "eager" : (lazy ? "lazy" : "eager")}
      decoding="async"
      // fetchpriority is a recent (2023+) hint; browsers without
      // support fall through to the default queue order.
      fetchpriority={eager ? "high" : "auto"}
      onLoad={() => {
          setLoaded(true);
          if (onLoad) onLoad();
          if (typeof performance === "undefined") return;
          if (eager && source) {
            // Eager perf signal (existing behaviour) — render→onLoad.
            const ms = Math.round(performance.now() - loadStart);
            track("perf.card_image_load", {
              listing_id: listing.id,
              idx,
              ms,
              source,
            });
          } else if (!eager && source) {
            // Lazy perf signal — viewport-entry → onLoad. If load
            // beat intersection (native lazy fetched ahead of time),
            // we'll instead emit zero from the IO callback.
            lazyImgLoadedRef.current = true;
            if (lazyVisibleAtRef.current != null && !lazyEmittedRef.current) {
              lazyEmittedRef.current = true;
              const ms = Math.max(0, Math.round(performance.now() - lazyVisibleAtRef.current));
              track("perf.card_image_lazy_load", {
                listing_id: listing.id,
                idx,
                ms,
                source,
              });
            }
          }
        }}
        onError={() => {
          setErrored(true);
          // Telemetry — see events.ts "image.error". Wrapped in try/catch
          // so a telemetry hiccup never breaks the placeholder fallback.
          try {
            track("image.error", {
              url: String(url || "").slice(0, 200),
              listing_id: listing.id,
              idx,
              source: source || "unknown",
              is_local: String(url || "").startsWith("/photos/"),
            });
          } catch { /* ignore */ }
        }}
        style={{ opacity: loaded ? 1 : 0 }}
      />
  );
  return (
    <div ref={wrapRef} className={`photo-wrap ${className}`} style={{ aspectRatio: ratio }}>
      {!loaded && <div className="photo-skeleton" />}
      {optimized ? (
        <picture>
          {/* WebP variants. Modern browsers pick the smallest candidate
              that satisfies the sizes hint; <img src> below is the
              fallback for browsers that ignore <source> entirely. */}
          <source
            type="image/webp"
            srcSet={optimized.webpSrcSet}
            sizes={optimizedSizes}
          />
          {imgElement}
        </picture>
      ) : (
        imgElement
      )}
    </div>
  );
}

// ===== Heart / Save button =====
function HeartButton({ listingId, app, size = 18, variant = "overlay" }) {
  const saved = app.savedIds.has(listingId);
  const [pulse, setPulse] = useState(false);
  const onClick = (e) => {
    e.stopPropagation();
    e.preventDefault();
    if (!app.user) {
      app.openSignup({ pendingSave: listingId });
      return;
    }
    app.toggleSave(listingId);
    setPulse(true);
    setTimeout(() => setPulse(false), 200);
  };
  return (
    <button
      className={`heart-btn heart-${variant} ${saved ? "is-saved" : ""} ${pulse ? "pulse" : ""}`}
      onClick={onClick}
      aria-label={t(saved ? "card.heart.remove" : "card.heart.save", currentLocale())}
    >
      <svg width={size} height={size} viewBox="0 0 24 24"
           fill={saved ? "var(--accent-2)" : "none"}
           stroke={saved ? "var(--accent-2)" : "currentColor"}
           strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z"/>
      </svg>
    </button>
  );
}

// ===== Listing Card =====
// PR-photo-nav-perf — clicking the carousel arrows used to fire a
// fresh network fetch at click time, so the new photo took 200-500ms
// to appear on a typical connection. Two changes fix this:
//   1. PRELOAD: the card pre-fetches photos[1..MAX_PRELOAD] as soon as
//      it's hovered (desktop) or first seen (mobile). The browser
//      caches the bytes so the swap-in is near-instant on click.
//   2. EAGER: the currently-visible photo uses loading="eager" and
//      fetchpriority="high" — but ONLY when the caller marks the card
//      as `priority` (i.e. above-the-fold). Marking every card eager
//      is what was killing Browse-after-filter: 60 cards mounting at
//      once with high-priority hints saturates the priority lane and
//      cards above-the-fold stall behind off-screen requests.
//   3. TELEMETRY: card.photo_nav_latency captures click→render time
//      on arrow nav. perf.card_image_load (new) captures the initial
//      eager-load duration so we can spot Browse perf regressions in
//      PostHog.
const PHOTO_PRELOAD_MAX = 5;

function ListingCard({
  listing, app, compact = false, onOpen, variant = "default",
  priority = false, source, topRank,
}) {
  const [photoIdx, setPhotoIdx] = useState(0);
  const [hovered, setHovered] = useState(false);
  const navStartRef = useRef(null);    // performance.now() at last arrow click
  const navFromIdxRef = useRef(0);     // for the to_idx event payload
  const preloadedRef = useRef(false);  // gate: only preload once per card mount
  const isMag = variant === "magazine";
  const dropPct = listing.previous_price
    ? Math.round((1 - listing.price / listing.previous_price) * 100)
    : null;
  const daysText = formatDaysListed(listing.days_listed);
  const daysTone = daysListedTone(listing.days_listed);

  // Preload secondary photos on first hover so the carousel swap-in is
  // near-instant. We use new Image() so the browser pulls bytes into
  // its cache without rendering the elements; the actual <img> tag
  // later just hits the cache. Capped at PHOTO_PRELOAD_MAX so a
  // 50-photo listing doesn't slam the network with 49 concurrent
  // requests.
  useEffect(() => {
    if (!hovered || preloadedRef.current) return;
    if (typeof window === "undefined" || !listing.photos || listing.photos.length <= 1) return;
    preloadedRef.current = true;
    const toPreload = listing.photos.slice(1, 1 + PHOTO_PRELOAD_MAX);
    for (const url of toPreload) {
      const img = new window.Image();
      img.decoding = "async";
      img.src = url;
    }
  }, [hovered, listing.photos]);

  // Telemetry: when a new photo finishes loading after an arrow click,
  // emit the click→render latency. fired-once-per-click via the ref.
  const onPhotoLoaded = () => {
    if (navStartRef.current == null) return;
    const ms = Math.round(performance.now() - navStartRef.current);
    track("card.photo_nav_latency", {
      listing_id: listing.id,
      from_idx:   navFromIdxRef.current,
      to_idx:     photoIdx,
      ms,
    });
    navStartRef.current = null;
  };

  // Wraps setPhotoIdx so every arrow-click stamps the start time + the
  // previous index for the next onLoad event payload.
  const navigateTo = (nextIdx) => {
    navStartRef.current = performance.now();
    navFromIdxRef.current = photoIdx;
    setPhotoIdx(nextIdx);
  };

  const handleClick = (e) => {
    if (onOpen) onOpen(listing);
  };

  // Crawlable + middle-click-friendly anchor over the card. The card's
  // existing onClick still drives the SPA on bare left-click; the anchor
  // is what Googlebot follows + what cmd-click / middle-click pick up.
  // Modifier-key clicks fall through to the browser's native handling
  // (open in new tab); plain left-clicks call openListing as today.
  const cardHref = `/listing/${encodeURIComponent(listing.id)}`;
  const onCardAnchorClick = (e) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    if (onOpen) onOpen(listing);
  };

  return (
    <article
      className={`listing-card ${compact ? "compact" : ""} ${isMag ? "listing-card-magazine" : ""}`}
      onClick={handleClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* SEO + middle-click anchor. aria-hidden + tabIndex=-1 keep it
          out of the keyboard tab order — the card itself stays the
          interactive target. The anchor sits behind interactive
          children (heart, photo arrows) so those still get pointer
          events first; everywhere else it gives Google a real <a>. */}
      <a
        className="listing-card-anchor"
        href={cardHref}
        onClick={onCardAnchorClick}
        aria-hidden="true"
        tabIndex={-1}
      />
      <div className="listing-card-photo">
        <Photo
          listing={listing}
          idx={photoIdx}
          ratio={isMag ? "4/3" : "16/9"}
          eager={priority}
          source={source}
          onLoad={onPhotoLoaded}
          thumbnail={photoIdx === 0}
        />
        {topRank != null && (
          <span className="pulpo-rank listing-card-rank" aria-label={`Pulpo ranked ${topRank}`}>
            <span className="pulpo-rank-star" aria-hidden="true">
              <RankTrophy />
            </span>
            <span className="pulpo-rank-num">{topRank}</span>
          </span>
        )}
        <div className="card-badge-row">
          <Badge listing={listing} />
        </div>
        <HeartButton listingId={listing.id} app={app} variant="overlay" size={18} />
        {hovered && listing.photos.length > 1 && (
          <>
            <button className="photo-nav prev"
              onClick={(e) => { e.stopPropagation(); navigateTo((photoIdx - 1 + listing.photos.length) % listing.photos.length); }}
              aria-label={t("card.photo.prev", currentLocale())}>
              <Icon name="chevron_left" size={18} strokeWidth={2} />
            </button>
            <button className="photo-nav next"
              onClick={(e) => { e.stopPropagation(); navigateTo((photoIdx + 1) % listing.photos.length); }}
              aria-label={t("card.photo.next", currentLocale())}>
              <Icon name="chevron_right" size={18} strokeWidth={2} />
            </button>
            <div className="photo-dots">
              {listing.photos.slice(0, 6).map((_, i) => (
                <span key={i} className={i === photoIdx ? "active" : ""} />
              ))}
            </div>
          </>
        )}
      </div>
      <div className="listing-card-body">
        <h3 className="listing-card-title">{tr(listing.title, currentLocale())}</h3>
        <div className="listing-card-meta">
          {listing.zone_name} · {landTypeLabel(listing.land_type)}
        </div>
        <div className="listing-card-price">
          <span
            className={listing.price == null ? "price-main muted" : "price-main"}
            title={listing.price == null ? t("value.notshared.tooltip", currentLocale()) : undefined}
          >{formatPrice(listing.price)}</span>
          {listing.previous_price && (
            <span className="price-was">{formatPrice(listing.previous_price)}</span>
          )}
          {!isMag && (() => {
            // Size + ppm sub-row. When either price or size is null,
            // ppm is meaningless (it's derived). Drop it cleanly so
            // the user sees "· Not shared" once, not twice.
            const sizeMissing = listing.size_m2 == null;
            const ppmAvailable = listing.price != null && listing.size_m2 != null && listing.price_per_m2 != null;
            return (
              <span className="price-sub">
                · <span title={sizeMissing ? t("value.notshared.tooltip", currentLocale()) : undefined}>{formatSize(listing.size_m2)}</span>
                {ppmAvailable && ` · ${formatPpm(listing.price_per_m2)}${ppmSuffix()}`}
              </span>
            );
          })()}
        </div>
        {!compact && !isMag && listing.usps[0] && (() => {
          // Same gate the detail panel uses — keep card and detail in
          // lockstep via lib/gating.ts. Anonymous + Free see 1, paid
          // see all. Cap is enforced via slice() so a user with 0
          // visible reasons (theoretical) renders nothing rather than
          // crashing on `usps[-1]`.
          const visible = listing.usps.slice(0, uspsVisibleFor(app?.user));
          if (visible.length === 0) return null;
          return (
            <ul className="listing-card-usps">
              {visible.map((u, i) => (
                <li key={i}>
                  <Icon name="check" size={13} strokeWidth={2.4} />
                  {tr(u, currentLocale())}
                </li>
              ))}
            </ul>
          );
        })()}
        {!isMag && (
          <div className="listing-card-footer">
            {(() => {
              const sid = listing.source_id;
              const isSocialOffMarket = sid === "whatsapp" || sid === "facebook";
              const sourceText = isSocialOffMarket ? t("badge.off_market", currentLocale()) : listing.source_label;
              return <span className="source-pill" title={sourceText}>{sourceText}</span>;
            })()}
            {daysText && <span className={`days-pill tone-${daysTone}`}>{daysText}</span>}
          </div>
        )}
      </div>
    </article>
  );
}

// ===== Skeleton card =====
function SkeletonCard() {
  return (
    <div className="listing-card skeleton">
      <div className="listing-card-photo skel-photo" />
      <div className="listing-card-body">
        <div className="skel-line w-80" />
        <div className="skel-line w-50" />
        <div className="skel-line w-60" />
      </div>
    </div>
  );
}

// ===== Toast =====
function Toast({ toast }) {
  if (!toast) return null;
  return (
    <div className="toast" key={toast.id}>
      <Icon name="check" size={16} strokeWidth={2.4} />
      <span>{toast.message}</span>
    </div>
  );
}

export {
  Icon, RankTrophy, PulpoLogo, PulpoMark, Badge, Photo, HeartButton, ListingCard, SkeletonCard, Toast,
  formatPrice, formatSize, formatDaysListed, formatPpm, ppmSuffix,
  daysListedTone, landTypeLabel, formatDistanceKm, currentLocale, currentUnits,
};
