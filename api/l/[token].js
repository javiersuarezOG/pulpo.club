// GET /l/<token> — source-opaque share landing page.
//
// Public, no auth. Decodes the base64url token to the internal listing
// id (see web/app/lib/share.ts), looks up the listing in ranked.json,
// and returns the SPA shell with per-listing og:title / og:description
// / og:image / og:url meta tags injected at the <!--OG_TAGS--> sentinel.
//
// Browsers ignore the duplicate-prepended meta tags (the OG spec says
// the LAST tag wins, and the SPA itself doesn't rewrite them). Crawlers
// (facebookexternalhit, WhatsApp, Twitterbot, Discordbot, LinkedInBot,
// iMessageLinkPreview, Slackbot, TelegramBot) read the injected tags
// and render the rich link preview tile.
//
// Source-opacity (CLAUDE.md): none of the injected strings reference
// the broker. og:title/description are derived from listing.title,
// listing.price_usd, listing.dist_beach_km, and i18n hook templates.
// og:image points to /api/social/card?token=… which itself reads only
// derived/normalized fields.

const fs = require("fs");
const path = require("path");

// Same alphabet / safety check as web/app/lib/share.ts.
const TOKEN_RE = /^[A-Za-z0-9_-]+$/;
const SAFE_LISTING_ID_RE = /^[A-Za-z0-9._\-]+$/;

function decodeShareToken(token) {
  if (!TOKEN_RE.test(token)) return null;
  try {
    const padded = token.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = Buffer.from(padded, "base64").toString("utf-8");
    return SAFE_LISTING_ID_RE.test(decoded) ? decoded : null;
  } catch {
    return null;
  }
}

// ── Disk-resident asset loaders ──────────────────────────────────────
// Both ranked.json and the SPA shell live in the deployment bundle
// (this function's __dirname is api/l/, so we walk up two levels).
// Cached at process start since Vercel serverless containers stay
// warm; nightly redeploys naturally invalidate.

let cachedShellHtml = null;
function loadShellHtml() {
  if (cachedShellHtml) return cachedShellHtml;
  const candidates = [
    path.join(__dirname, "..", "..", "web", "dist", "index.html"),
    path.join(process.cwd(), "web", "dist", "index.html"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      cachedShellHtml = fs.readFileSync(c, "utf-8");
      return cachedShellHtml;
    }
  }
  return null;
}

let cachedRanked = null;
let cachedRankedMtime = 0;
function loadRanked() {
  const candidates = [
    path.join(__dirname, "..", "..", "web", "data", "ranked.json"),
    path.join(process.cwd(), "web", "data", "ranked.json"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      const stat = fs.statSync(c);
      if (cachedRanked && stat.mtimeMs === cachedRankedMtime) return cachedRanked;
      cachedRanked = JSON.parse(fs.readFileSync(c, "utf-8"));
      cachedRankedMtime = stat.mtimeMs;
      return cachedRanked;
    }
  }
  return null;
}

function findListing(id) {
  const rows = loadRanked();
  if (!Array.isArray(rows)) return null;
  for (const row of rows) {
    if (`${row.source}__${row.source_id}` === id) return row;
  }
  return null;
}

// ── Caption building ─────────────────────────────────────────────────
// Mirrors web/app/lib/share.ts + api/social/card.js so all three
// surfaces (SharePicker text pre-fill, og:title/description, OG card
// chip) say the same thing in the same voice.

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
  if (n == null || !Number.isFinite(n)) return null;
  return `$${Math.round(n).toLocaleString("en-US")}`;
}

function buildOgFields({ listing, token, lang, baseUrl }) {
  const title = String(listing.title || "").trim();
  const price = formatPrice(listing.price_usd);
  const hook = captionHook(listing, lang);
  const area = listing.area_m2 ? `${Math.round(listing.area_m2).toLocaleString("en-US")} m²` : null;
  const loc = listing.department || listing.municipality || "";

  // og:title — title + price. Width-budget for the OG-tile bold line.
  const ogTitle = price ? `${title} — ${price}` : title;

  // og:description — size + hook + location, " · "-joined. Empty parts
  // are skipped so the line never has dangling separators.
  const descParts = [area, hook, loc].filter(Boolean);
  const ogDescription = descParts.join(" · ");

  return {
    ogTitle,
    ogDescription,
    ogImage: `${baseUrl}/api/social/card?token=${encodeURIComponent(token)}${lang === "es" ? "&lang=es" : ""}`,
    ogUrl: `${baseUrl}/l/${encodeURIComponent(token)}`,
  };
}

// HTML entity escape for safe injection into meta `content="…"` attrs.
function escapeAttr(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function buildOgMetaBlock({ ogTitle, ogDescription, ogImage, ogUrl }) {
  // Prepended via the SENTINEL replace below. The static og:title/
  // og:description in web/index.html stay above this block; the
  // crawler-spec behavior is "last property wins" so our per-listing
  // tags override the site-level defaults without removing them.
  return [
    `<meta property="og:title" content="${escapeAttr(ogTitle)}" />`,
    `<meta property="og:description" content="${escapeAttr(ogDescription)}" />`,
    `<meta property="og:image" content="${escapeAttr(ogImage)}" />`,
    `<meta property="og:image:width" content="1200" />`,
    `<meta property="og:image:height" content="630" />`,
    `<meta property="og:url" content="${escapeAttr(ogUrl)}" />`,
    `<meta property="og:type" content="website" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${escapeAttr(ogTitle)}" />`,
    `<meta name="twitter:description" content="${escapeAttr(ogDescription)}" />`,
    `<meta name="twitter:image" content="${escapeAttr(ogImage)}" />`,
  ].join("\n    ");
}

// ── Base URL discipline ──────────────────────────────────────────────
// Same logic as api/social/image.js cdnBaseUrl(): the production alias
// bypasses Vercel Deployment Protection (SSO), VERCEL_URL does NOT, so
// embedding VERCEL_URL into og:image would 401 every WhatsApp crawler.
function publicBaseUrl(req) {
  if (process.env.PULPO_PUBLIC_BASE_URL) return process.env.PULPO_PUBLIC_BASE_URL;
  return "https://pulpo.club";
}

// Language detection from Accept-Language. Pulpo ships en + es; any
// es-* (es-MX, es-SV, es-ES) lands as "es", everything else as "en".
function detectLang(req) {
  const header = (req.headers && req.headers["accept-language"]) || "";
  return /\bes\b|^es-/i.test(header) ? "es" : "en";
}

// Vercel Node handler. async to fit the API contract; the body of work
// is sync but Vercel hooks accept both.
module.exports = async (req, res) => {
  // Pull the token from the dynamic param OR the path tail — Vercel
  // sometimes passes /api/l/[token] params via req.query.token, but a
  // direct fetch test from curl can land us here without it.
  let token = (req.query && req.query.token) || "";
  if (!token && req.url) {
    const m = req.url.match(/\/l\/([^/?#]+)/);
    if (m) token = decodeURIComponent(m[1]);
  }

  const id = decodeShareToken(token);
  if (!id) {
    res.statusCode = 404;
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.end("not found");
    return;
  }

  const shell = loadShellHtml();
  if (!shell) {
    // The build hasn't happened (e.g. local Vercel dev with no
    // preceding vite build). Bail cleanly so the user sees a real
    // error instead of a half-rendered page.
    res.statusCode = 500;
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.end("SPA shell not found on disk — run `npm run build`");
    return;
  }

  const listing = findListing(id);
  if (!listing) {
    // Listing was scraped + removed (relisted, sold, broker took it
    // down). Return the bare SPA shell so the user lands on the
    // homepage rather than a 404 wall. Crawlers see the site-level OG.
    res.statusCode = 200;
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.setHeader("Cache-Control", "public, s-maxage=300");
    res.end(shell);
    return;
  }

  const lang = detectLang(req);
  const baseUrl = publicBaseUrl(req);
  const og = buildOgFields({ listing, token, lang, baseUrl });
  const metaBlock = buildOgMetaBlock(og);

  // Replace the literal sentinel comment with our meta block. If a
  // future Vite build strips comments, this becomes a no-op (silent
  // fall-through to site-level OG) — added a CI guard via the
  // smoke test below.
  const html = shell.replace("<!--OG_TAGS-->", metaBlock);

  res.statusCode = 200;
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.setHeader("Cache-Control", "public, s-maxage=3600, stale-while-revalidate=86400");
  res.end(html);
};

// Exported for unit tests. NOT part of the public Vercel API surface.
module.exports._internal = { decodeShareToken, captionHook, buildOgFields, escapeAttr };
