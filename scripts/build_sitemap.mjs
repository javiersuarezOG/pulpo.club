#!/usr/bin/env node
// Build-time sitemap generator.
//
// robots.txt advertises https://pulpo.club/sitemap.xml; without this
// script the URL 404s and Search Console flags it during the launch
// indexing window. Reads web/data/ranked.list.json (the slim list
// served to the FE) and emits one <url> per listing plus the static
// section paths.
//
// Wired into `npm run build` (package.json) so every Vite build —
// local, preview, prod — produces a fresh sitemap. Vercel's static
// rewrite at /sitemap.xml → /web/sitemap.xml then serves it.
//
// Listing IDs follow the same `${source}__${source_id}` shape the
// FE adapter (web/app/data/listings.ts:163) uses for /listing/:id —
// any drift here and the sitemap links 404.

import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const REPO     = path.dirname(path.dirname(url.fileURLToPath(import.meta.url)));
const SRC      = path.join(REPO, "web/data/ranked.list.json");
const OUT      = path.join(REPO, "web/sitemap.xml");
const HOST     = "https://pulpo.club";

// Static SPA section paths Googlebot should index, with per-path
// changefreq + priority. Mirrors SECTION_ENTRIES in
// automation/sitemap.py — the nightly pipeline regenerates the sitemap
// via the Python generator, but every Vercel deploy runs THIS script
// and overwrites the file, so the two MUST agree. Drift means category
// routes + hreflang alternates disappear from prod between nightlies.
//
// Category keys mirror CATEGORY_KEYS in web/app/lib/categories.ts;
// each one must have matching localized title/description copy in
// web/app/lib/use-document-meta.ts's BROWSE_CATEGORY_COPY map.
//
// /admin and /api/* are robots-disallowed and intentionally omitted.
// /saved + /account require auth — also omitted (Google indexing them
// adds no value for anon users).
const STATIC_ENTRIES = [
  // [path, changefreq, priority]
  ["/",                                "daily",   "1.0"],
  ["/browse",                          "daily",   "0.9"],
  // High-intent category landing pages:
  ["/browse?cat=beachfront",           "daily",   "0.9"],
  ["/browse?cat=build_ready",          "daily",   "0.8"],
  ["/browse?cat=ocean_view",           "daily",   "0.8"],
  ["/browse?cat=water_features",       "weekly",  "0.7"],
  ["/browse?cat=commercial",           "weekly",  "0.7"],
  ["/browse?cat=under_50k",            "daily",   "0.7"],
  ["/browse?cat=under_100k",           "daily",   "0.7"],
  // Refinement filters:
  ["/browse?cat=mountain_view",        "weekly",  "0.6"],
  ["/browse?cat=flat_buildable",       "weekly",  "0.6"],
  ["/browse?cat=best_documented",      "weekly",  "0.6"],
  // Time-bounded shelves:
  ["/browse?cat=new_this_week",        "daily",   "0.6"],
  ["/browse?cat=price_drops",          "daily",   "0.6"],
  ["/browse?cat=motivated_sellers",    "weekly",  "0.5"],
  // Paywalled — crawlable but lower priority:
  ["/browse?cat=off_market",           "weekly",  "0.6"],
  ["/plans",                           "monthly", "0.5"],
  ["/start",                           "weekly",  "0.6"],
  ["/terms",                           "yearly",  "0.3"],
  ["/privacy",                         "yearly",  "0.3"],
  ["/cookies",                         "yearly",  "0.3"],
  ["/subscription",                    "yearly",  "0.3"],
  ["/imprint",                         "yearly",  "0.3"],
  ["/contact",                         "monthly", "0.4"],
];

function xmlEscape(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function listingId(row) {
  const source   = String(row.source || "").trim();
  const sourceId = String(row.source_id || "").trim();
  if (!source || !sourceId) return null;
  return `${source}__${sourceId}`;
}

// Build a <url> entry with EN/ES/x-default hreflang alternates.
// Pulpo serves Spanish on the same path via `?lang=es`; Google needs
// explicit hreflang to avoid treating the variants as duplicate content.
function urlEntry(loc, opts = {}) {
  const sep = loc.includes("?") ? "&" : "?";
  const enUrl = `${HOST}${loc}`;
  const esUrl = `${HOST}${loc}${sep}lang=es`;
  const lines = [
    "  <url>",
    `    <loc>${xmlEscape(enUrl)}</loc>`,
  ];
  if (opts.lastmod)    lines.push(`    <lastmod>${xmlEscape(opts.lastmod)}</lastmod>`);
  if (opts.changefreq) lines.push(`    <changefreq>${xmlEscape(opts.changefreq)}</changefreq>`);
  if (opts.priority != null) lines.push(`    <priority>${opts.priority}</priority>`);
  lines.push(`    <xhtml:link rel="alternate" hreflang="en" href="${xmlEscape(enUrl)}"/>`);
  lines.push(`    <xhtml:link rel="alternate" hreflang="es" href="${xmlEscape(esUrl)}"/>`);
  lines.push(`    <xhtml:link rel="alternate" hreflang="x-default" href="${xmlEscape(enUrl)}"/>`);
  lines.push("  </url>");
  return lines.join("\n");
}

function main() {
  let rows = [];
  try {
    rows = JSON.parse(fs.readFileSync(SRC, "utf8"));
    if (!Array.isArray(rows)) rows = [];
  } catch (err) {
    // Missing or malformed data file — emit a sitemap with just the
    // static paths so /sitemap.xml never 404s. The nightly pipeline
    // regenerates ranked.list.json; once it lands, the next build
    // picks it up.
    console.warn(`[build_sitemap] ${SRC} unreadable: ${err.message} — falling back to static paths only`);
  }

  const today = new Date().toISOString().slice(0, 10);
  const entries = [];

  for (const [path, changefreq, priority] of STATIC_ENTRIES) {
    entries.push(urlEntry(path, { lastmod: today, changefreq, priority }));
  }

  let listingCount = 0;
  for (const row of rows) {
    // Skip off-market — paywalled, don't surface them in the public
    // sitemap so Google doesn't index URLs anon users can't read.
    // Skip sold — dead URLs.
    if (row.source_type === "off_market") continue;
    if (row.is_sold) continue;
    const id = listingId(row);
    if (!id) continue;
    entries.push(urlEntry(`/listing/${encodeURIComponent(id)}`, {
      lastmod:    today,
      changefreq: "weekly",
      priority:   "0.7",
    }));
    listingCount++;
  }

  const xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
    '        xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    entries.join("\n"),
    "</urlset>",
    "",
  ].join("\n");

  fs.writeFileSync(OUT, xml, "utf8");
  console.log(`[build_sitemap] wrote ${OUT} — ${STATIC_ENTRIES.length} static + ${listingCount} listings`);
}

main();
