#!/usr/bin/env node
/* verify_shelf_counts.mjs — sanity check for the live-data adapter.
 *
 * Runs the shelf filters from the FE registry against the real
 * web/data/ranked.json and prints per-shelf counts. PR-3+ uses this to
 * cross-check that the adapter produces the same counts the FE shows.
 *
 * Usage: node scripts/verify_shelf_counts.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const rankedPath = resolve(here, "../web/data/ranked.json");
const raw = JSON.parse(readFileSync(rankedPath, "utf-8"));

// Mirror the adapter's source-type rule (off-market sources hidden).
const OFF_MARKET = new Set(["whatsapp", "facebook", "private"]);

function days(iso) {
  if (!iso) return 0;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? Math.floor((Date.now() - t) / 86_400_000) : 0;
}

const adapted = raw.map((r) => ({
  ...r,
  source_type: OFF_MARKET.has(r.source) ? "off_market" : "on_market",
  beachfront_tier: r.is_beachfront ? "near_beach" : null,
  first_seen_date: days(r.first_seen_at),
  is_sold: false,
}));

// Same filter recipes as web/app/data.jsx SHELVES.
const shelves = {
  new_this_week: (l) => l.first_seen_date <= 7,
  price_drops: (l) => l.is_repriced,
  off_market: (l) => l.source_type === "off_market",
  best_documented: (l) => (l.photos_count ?? 0) >= 8,
  beachfront: (l) => l.beachfront_tier !== null,
  ocean_view: (l) => l.has_ocean_view && !l.beachfront_tier,
  mountain_view: (l) => l.has_mountain_view,
  water_features: (l) => l.has_water_body,
  flat_buildable: (l) => l.is_flat,
  build_ready: (l) => (l.readiness_score ?? 0) >= 3,
  commercial: (l) => l.land_type === "commercial",
  under_50k: (l) => (l.price_usd ?? Infinity) <= 50_000,
  under_100k: (l) =>
    (l.price_usd ?? Infinity) <= 100_000 && (l.price_usd ?? 0) > 50_000,
  motivated_sellers: (l) => (l.days_listed ?? 0) >= 90,
};

console.log(`Shelf counts (n=${adapted.length} listings)\n`);
for (const [key, predicate] of Object.entries(shelves)) {
  const count = adapted.filter(predicate).length;
  const flag = count >= 6 ? "" : " (hidden — <6)";
  console.log(`  ${key.padEnd(20)} ${String(count).padStart(4)}${flag}`);
}
