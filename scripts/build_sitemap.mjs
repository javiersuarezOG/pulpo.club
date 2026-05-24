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

// Static SPA section paths Googlebot should index. Mirrors the routes
// in vercel.json's rewrites + web/robots.txt's allow set. /admin and
// /api/* are robots-disallowed and intentionally omitted here.
const STATIC_PATHS = [
  "/", "/browse", "/saved", "/plans", "/start",
  "/terms", "/privacy", "/cookies", "/imprint", "/contact",
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

function urlEntry(loc, opts = {}) {
  const lines = [
    "  <url>",
    `    <loc>${xmlEscape(loc)}</loc>`,
  ];
  if (opts.lastmod)    lines.push(`    <lastmod>${xmlEscape(opts.lastmod)}</lastmod>`);
  if (opts.changefreq) lines.push(`    <changefreq>${xmlEscape(opts.changefreq)}</changefreq>`);
  if (opts.priority != null) lines.push(`    <priority>${opts.priority}</priority>`);
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

  for (const p of STATIC_PATHS) {
    entries.push(urlEntry(`${HOST}${p}`, {
      lastmod:    today,
      changefreq: p === "/" ? "daily" : "weekly",
      priority:   p === "/" ? "1.0" : "0.7",
    }));
  }

  let listingCount = 0;
  for (const row of rows) {
    const id = listingId(row);
    if (!id) continue;
    entries.push(urlEntry(`${HOST}/listing/${encodeURIComponent(id)}`, {
      lastmod:    today,
      changefreq: "weekly",
      priority:   "0.6",
    }));
    listingCount++;
  }

  const xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    entries.join("\n"),
    "</urlset>",
    "",
  ].join("\n");

  fs.writeFileSync(OUT, xml, "utf8");
  console.log(`[build_sitemap] wrote ${OUT} — ${STATIC_PATHS.length} static + ${listingCount} listings`);
}

main();
