// GET /api/social/card — 1200×630 share-card PNG.
//
// Public, edge-cached. Crawlers (WhatsApp, FB, iMessage, Discord, etc.)
// fetch this URL from the og:image meta tag injected by api/l/[token].js
// and render the result as the link preview tile.
//
// Query params:
//   token   base64url(`<source>__<source_id>`)   required
//   lang    en | es                              default en
//
// Rendered with @vercel/og (Satori → Resvg → PNG). Edge runtime so
// cold-start is fast for the crawler-bursty traffic pattern.
//
// Source-opacity (CLAUDE.md): the rendered card NEVER includes
// `listing.source` / `listing.source_label`. All copy is derived from
// title, price, distance fields, and i18n templates. The only brand
// chrome is Pulpo's wordmark + octopus mark.
//
// Caching strategy: content-addressed by (token, lang). The token
// alone is enough — when a listing's price/photo changes, ranked.json
// is regenerated nightly and its CDN cache rolls over, so the next
// crawler fetch picks up fresh data on stale-while-revalidate.

import React from "react";
import { ImageResponse } from "@vercel/og";

// Vercel API functions use the classic JSX runtime by default (no
// automatic-import). `import React` here is mandatory for esbuild to
// resolve the JSX factory; without it the deploy build errors out with
// "React is not defined" before the function ever boots.
export const config = { runtime: "edge" };

// Same alphabet check as web/app/lib/share.ts. Keep in sync.
const TOKEN_RE = /^[A-Za-z0-9_-]+$/;
const SAFE_LISTING_ID_RE = /^[A-Za-z0-9._\-]+$/;

function decodeShareToken(token) {
  if (!TOKEN_RE.test(token)) return null;
  try {
    const padded = token.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = atob(padded);
    return SAFE_LISTING_ID_RE.test(decoded) ? decoded : null;
  } catch {
    return null;
  }
}

// Mirrors PULPO_PUBLIC_BASE_URL discipline from api/social/image.js —
// VERCEL_URL is the deployment-specific URL which is SSO-gated on this
// project, so fetching from it returns a 401 challenge instead of JSON.
// The production alias bypasses Deployment Protection by design.
function cdnBaseUrl() {
  if (process.env.PULPO_PUBLIC_BASE_URL) return process.env.PULPO_PUBLIC_BASE_URL;
  return "https://pulpo.club";
}

// Edge can't read disk; ranked.json comes from the deployment CDN.
// Cached at the Vercel edge between calls, so the per-card cost is one
// extra ~1ms hop after the first warm hit.
async function fetchListing(id) {
  const url = `${cdnBaseUrl()}/data/ranked.json`;
  const resp = await fetch(url, { cf: { cacheTtl: 300 } });
  if (!resp.ok) return null;
  const rows = await resp.json();
  if (!Array.isArray(rows)) return null;
  for (const row of rows) {
    if (`${row.source}__${row.source_id}` === id) return row;
  }
  return null;
}

// Title-case a slug like "el-tunco" → "Playa El Tunco". The "Playa "
// prefix is added when the zone is a known beach; lakes get "Lago",
// other zones fall back to the slug.
function zoneDisplayName(zone) {
  if (!zone) return "";
  const titled = zone.split("-").map((w) => w[0]?.toUpperCase() + w.slice(1)).join(" ");
  return titled;
}

// Same hook copy as the share caption — keeps WhatsApp's text preview
// and OG-image-rendered chip identical so the user sees one consistent
// message. Walk > short drive > lake > generic, exactly like
// SharePicker's captionHook.
function captionHook(listing, lang) {
  const km = listing.dist_beach_km;
  if (listing.is_walk_to_beach && typeof km === "number" && km < 1) {
    const minutes = Math.max(5, Math.round((km * 12) / 5) * 5);
    return lang === "es" ? `${minutes} min a pie a la playa` : `${minutes} min walk to beach`;
  }
  if (typeof km === "number" && km > 0 && km < 5) {
    const k = Math.round(km);
    return lang === "es" ? `a ${k} km de la playa` : `${k} km from the beach`;
  }
  if (listing.is_on_lake) return lang === "es" ? "Frente al lago" : "On the lake";
  return lang === "es" ? "En Pulpo" : "On Pulpo";
}

function formatPrice(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  return `$${Math.round(n).toLocaleString("en-US")}`;
}

function formatPpm(n) {
  if (n == null || !Number.isFinite(n) || n <= 0) return null;
  return `$${Math.round(n)}/m²`;
}

// Continuity contract (PR #785): lead with the hero picker's winning
// broker URL when present, so the OG card the user clicks matches the
// first image the detail gallery shows on arrival. Falls back to the
// raw first photo when the field is missing (older listings, or the
// winner is already photo_urls[0]).
function pickPhotoUrl(listing) {
  if (typeof listing.selected_photo_url === "string" && listing.selected_photo_url.startsWith("http")) {
    return listing.selected_photo_url;
  }
  return (Array.isArray(listing.photo_urls) && listing.photo_urls[0]) ? listing.photo_urls[0] : null;
}

// Render the OG card image. React.createElement (not JSX) so the file
// stays as plain .js — Vercel's serverless function classifier only
// auto-detects .js / .ts / .mjs / .cjs in api/; .jsx/.tsx in this
// directory layout fall through with "doesn't match any Serverless
// Functions" at deploy time. Satori receives the createElement tree
// directly, no transpilation needed.
//
// Constraints (Satori CSS subset): flex layouts only, no `display: block`
// on text nodes, no transforms beyond translate/rotate/scale.
const h = React.createElement;

function renderCard({ listing, lang }) {
  const title = String(listing.title || "").trim();
  const price = formatPrice(listing.price_usd);
  const ppm = formatPpm(listing.price_per_m2);
  const hook = captionHook(listing, lang);
  const zone = zoneDisplayName(listing.zone || listing.zone_name);
  const muni = listing.municipality || "";
  const dept = listing.department || "";
  const area = listing.area_m2 ? `${Math.round(listing.area_m2).toLocaleString("en-US")} m²` : null;

  const features = [];
  if (listing.has_ocean_view) features.push(lang === "es" ? "vista al mar" : "ocean view");
  if (listing.has_power) features.push(lang === "es" ? "luz" : "power");
  if (listing.has_water) features.push(lang === "es" ? "agua" : "water");
  if (listing.is_flat) features.push(lang === "es" ? "plano" : "flat");

  const photoUrl = pickPhotoUrl(listing);

  const titleLine = area ? `${title} · ${area}` : title;
  const metaParts = [muni, dept, features.join(" · ")].filter(Boolean);

  // Full-bleed hero photo. Satori fetches the URL server-side at
  // render time; null on missing photo leaves the dark bg.
  const photo = photoUrl
    ? h("img", {
        src: photoUrl,
        width: 1200,
        height: 630,
        style: { position: "absolute", inset: 0, objectFit: "cover", width: 1200, height: 630 },
      })
    : null;

  // Two-stop gradient — dark at top + dark at bottom for text legibility.
  const gradient = h("div", {
    style: {
      position: "absolute",
      inset: 0,
      display: "flex",
      background:
        "linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 50%, rgba(0,0,0,0.82) 100%)",
    },
  });

  // Pulpo brand pill, top-right — the only attribution on the card.
  // Octopus mark path matches web/app/components.jsx PulpoMark.
  const brandPill = h(
    "div",
    {
      style: {
        position: "absolute",
        top: 32,
        right: 36,
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 22px 10px 12px",
        backgroundColor: "rgba(255,255,255,0.96)",
        borderRadius: 999,
        boxShadow: "0 4px 16px rgba(0,0,0,0.25)",
      },
    },
    h(
      "svg",
      { width: 36, height: 36, viewBox: "-50 -50 100 100" },
      h("circle", { cx: 0, cy: 0, r: 18, fill: "#1F4A3E" }),
      h("path", {
        d: "M -38 0 C -38 -21, -21 -38, 0 -38 C 21 -38, 38 -21, 38 0 C 38 17, 24 30, 7 30 C -8 30, -18 18, -18 4 C -18 -8, -8 -18, 4 -18 C 12 -18, 18 -12, 18 -4",
        stroke: "#1F4A3E",
        strokeWidth: 8.5,
        strokeLinecap: "round",
        fill: "none",
      }),
      h("circle", { cx: 18, cy: -4, r: 9.5, fill: "#1F4A3E" }),
      h("circle", { cx: 18, cy: -4, r: 5.5, fill: "#B8814A" }),
    ),
    h(
      "span",
      { style: { fontFamily: "Instrument Serif", fontSize: 30, color: "#1A1916", lineHeight: 1 } },
      "pulpo",
    ),
  );

  // Beach / hook chip — translucent glass pill at top of bottom stack.
  const chip = h(
    "div",
    {
      style: {
        display: "flex",
        alignItems: "center",
        alignSelf: "flex-start",
        gap: 10,
        padding: "10px 18px 10px 14px",
        marginBottom: 22,
        backgroundColor: "rgba(255,255,255,0.18)",
        border: "1px solid rgba(255,255,255,0.32)",
        borderRadius: 999,
        color: "#FFFFFF",
        fontSize: 22,
        fontWeight: 500,
      },
    },
    h("div", {
      style: {
        width: 10,
        height: 10,
        borderRadius: 999,
        backgroundColor: "#6BE38D",
        boxShadow: "0 0 14px rgba(107,227,141,0.8)",
      },
    }),
    zone ? `${hook} · ${zone}` : hook,
  );

  // Price — big serif with optional ppm badge alongside.
  const priceBlock = h(
    "div",
    { style: { display: "flex", alignItems: "flex-end", gap: 22, marginBottom: 14 } },
    h(
      "span",
      {
        style: {
          fontFamily: "Instrument Serif",
          fontSize: 144,
          lineHeight: 0.95,
          letterSpacing: "-0.025em",
          color: "#FFFFFF",
        },
      },
      price,
    ),
    ppm
      ? h(
          "span",
          {
            style: {
              fontSize: 26,
              fontWeight: 500,
              color: "rgba(255,255,255,0.88)",
              marginBottom: 18,
            },
          },
          ppm,
        )
      : null,
  );

  // Title + size line.
  const titleBlock = h(
    "div",
    {
      style: {
        fontSize: 36,
        fontWeight: 500,
        lineHeight: 1.2,
        color: "#FFFFFF",
        marginBottom: 8,
        maxWidth: 1000,
        display: "flex",
      },
    },
    titleLine,
  );

  // Meta line — municipality / department / features.
  const metaBlock = metaParts.length > 0
    ? h(
        "div",
        {
          style: {
            fontSize: 24,
            lineHeight: 1.35,
            color: "rgba(255,255,255,0.9)",
            display: "flex",
          },
        },
        metaParts.join(" · "),
      )
    : null;

  // Bottom content stack — chip, price, title, meta.
  const bottomStack = h(
    "div",
    {
      style: {
        position: "absolute",
        left: 56,
        right: 56,
        bottom: 44,
        display: "flex",
        flexDirection: "column",
        color: "#FFFFFF",
      },
    },
    chip,
    priceBlock,
    titleBlock,
    metaBlock,
  );

  // Root card container.
  return h(
    "div",
    {
      style: {
        width: 1200,
        height: 630,
        display: "flex",
        position: "relative",
        backgroundColor: "#111",
        fontFamily: "Inter",
      },
    },
    photo,
    gradient,
    brandPill,
    bottomStack,
  );
}

// Lazy-load the brand fonts. Cached for the lifetime of the edge
// worker — subsequent invocations skip the fetch.
//
// Google's css2 endpoint serves a CSS file with one @font-face per
// charset. We grab the first `src: url(...)` (Latin) — the en/es copy
// on a Pulpo card never leaves that subset.
async function fetchGoogleFont(family, weight) {
  const url = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family)}:wght@${weight}&display=swap`;
  // Modern desktop UA so Google serves woff2 (Satori ≥0.10 supports it).
  const css = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15" },
  }).then((r) => r.text());
  const match = css.match(/src:\s*url\((https:\/\/[^)]+)\)/);
  if (!match) throw new Error(`font lookup failed for ${family} ${weight}`);
  const fontBytes = await fetch(match[1]).then((r) => r.arrayBuffer());
  return fontBytes;
}

let cachedFonts = null;
async function loadFonts() {
  if (cachedFonts) return cachedFonts;
  const [interRegular, interMedium, instrument] = await Promise.all([
    fetchGoogleFont("Inter", 400),
    fetchGoogleFont("Inter", 500),
    fetchGoogleFont("Instrument Serif", 400),
  ]);
  cachedFonts = [
    { name: "Inter", data: interRegular, weight: 400, style: "normal" },
    { name: "Inter", data: interMedium, weight: 500, style: "normal" },
    { name: "Instrument Serif", data: instrument, weight: 400, style: "normal" },
  ];
  return cachedFonts;
}

export default async function handler(req) {
  const url = new URL(req.url);
  const token = url.searchParams.get("token") || "";
  const lang = url.searchParams.get("lang") === "es" ? "es" : "en";

  const id = decodeShareToken(token);
  if (!id) {
    return new Response("bad token", { status: 400 });
  }

  const listing = await fetchListing(id);
  if (!listing) {
    return new Response("listing not found", { status: 404 });
  }

  try {
    const fonts = await loadFonts();
    return new ImageResponse(renderCard({ listing, lang }), {
      width: 1200,
      height: 630,
      fonts,
      headers: {
        "Cache-Control": "public, s-maxage=86400, stale-while-revalidate=604800",
      },
    });
  } catch (err) {
    // Last-resort fallback so the crawler still gets *something* on
    // render failure. Returning a 500 makes WhatsApp show "no preview";
    // a generic 1200×630 PNG would be better but is more code than the
    // marginal benefit justifies right now.
    return new Response(`render error: ${err && err.message}`, { status: 500 });
  }
}

// Pure helpers exposed for unit testing (no render, no fetch). Mirrors
// the `_internal` convention used by api/l/[token].js.
handler._internal = { pickPhotoUrl };
