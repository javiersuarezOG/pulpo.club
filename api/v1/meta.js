// GET /api/v1/meta — the vocabulary for building a query.
//
// Every channel needs to render choices before it can ask for listings:
// a Telegram bot builds a zone keyboard, an MCP client needs to know
// which zone slugs exist so an LLM can ground "near El Tunco" on a real
// value instead of inventing one, and the website already has this
// information in memory.
//
// Serving it means no adapter ever hardcodes a zone list. That matters
// because zone slugs are minted by the pipeline from broker text — the
// set genuinely grows, and a hardcoded copy in a bot is a silent
// staleness bug nobody notices until a user asks for a zone that
// "doesn't exist".
//
// Counts reflect what a caller would actually receive from
// /api/v1/listings with no filters: sold listings are excluded, and so
// are incomplete ones (missing price or size), matching the website's
// default. Otherwise a channel would show "Mizata (7)" and then return
// four results.
//
// Cache: public, max-age=60, s-maxage=600. The underlying data changes
// once nightly, so the CDN serves virtually every request and the
// function itself runs a handful of times a day.
//
// Response:
//   { country, generated_at, total,
//     zones: [{ slug, name, count }],           // desc by count
//     master_categories: [{ value, count }],
//     subcategories:     [{ value, count }],
//     discovery_tags:    [{ value, count }],
//     price_usd: { min, max } | null,
//     size_m2:   { min, max } | null }



// CommonJS, not TypeScript: a .ts function cannot reach outside api/ at
// any depth, and these need the shared core (docs/api-v1.md).
const { zoneName } = require("../_core.js");
const { loadCatalog, resolveCountry, SUPPORTED_COUNTRIES } = require("./_catalog.js");
const { makeRateLimiter, ipFromRequest, send429 } = require("../_rate_limit.js");
const { methodNotAllowed, logApi } = require("./_http.js");

const limiter = makeRateLimiter({
  windowMs: 60_000,
  maxAttempts: 60,
  name: "v1_meta",
});

/** Rows a caller could actually retrieve. Mirrors the website's default
 *  visibility rules (web/app/pages.jsx:applyFilters) so counts here and
 *  results there agree. */
function isVisible(row) {
  return row.is_sold !== true && row.is_incomplete !== true;
}

function countBy(rows, key) {
  const tally = new Map();
  for (const row of rows) {
    const value = row[key];
    if (typeof value !== "string" || !value) continue;
    tally.set(value, (tally.get(value) ?? 0) + 1);
  }
  return [...tally.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

function countTags(rows) {
  const tally = new Map();
  for (const row of rows) {
    const tags = row.discovery_tags;
    if (!Array.isArray(tags)) continue;
    for (const tag of tags) {
      if (typeof tag !== "string" || !tag) continue;
      tally.set(tag, (tally.get(tag) ?? 0) + 1);
    }
  }
  return [...tally.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

/** Min/max over a numeric field, or null when nothing usable is present.
 *  Null rather than [0, 0]: a channel rendering a price slider must be
 *  able to tell "no data" from "everything is free". */
function bounds(rows, key) {
  let min = Infinity;
  let max = -Infinity;
  for (const row of rows) {
    const value = row[key];
    if (typeof value !== "number" || !Number.isFinite(value)) continue;
    if (value < min) min = value;
    if (value > max) max = value;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  return { min, max };
}

function buildMeta(catalog) {
  const rows = catalog.rows.filter(isVisible);

  const zoneTally = countBy(rows, "zone");

  return {
    country: catalog.country,
    generated_at: catalog.generatedAt,
    total: rows.length,
    zones: zoneTally.map(({ value, count }) => ({
      slug: value,
      name: zoneName(value),
      count,
    })),
    master_categories: countBy(rows, "master_category"),
    subcategories: countBy(rows, "subcategory"),
    discovery_tags: countTags(rows),
    price_usd: bounds(rows, "price_usd"),
    size_m2: bounds(rows, "area_m2"),
  };
}

function handler(req, res) {
  const t0 = Date.now();

  if (req.method !== "GET") return methodNotAllowed(res, "GET");

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) return send429(res, rl, "v1_meta");

  const country = resolveCountry(req.query && req.query.country);
  if (!country) {
    logApi("v1_meta", { status: 400, reason: "unknown_country", ms: Date.now() - t0 });
    return res.status(400).json({
      error: "unknown_country",
      supported: SUPPORTED_COUNTRIES,
    });
  }

  const catalog = loadCatalog(country);
  if (!catalog) {
    // Never degrade to an empty payload: "no zones" and "the data did
    // not deploy" are indistinguishable to a channel, and only one of
    // them is an incident.
    logApi("v1_meta", { status: 503, country, ms: Date.now() - t0 });
    return res.status(503).json({ error: "data_unavailable" });
  }

  const meta = buildMeta(catalog);

  res.setHeader("Cache-Control", "public, max-age=60, s-maxage=600, stale-while-revalidate=3600");
  logApi("v1_meta", { status: 200, country, zones: meta.zones.length, total: meta.total, ms: Date.now() - t0 });
  return res.status(200).json(meta);
}

module.exports = handler;
module.exports.buildMeta = buildMeta;

// Test seam. Re-exported from the handler so specs mutate the SAME
// module instance the handler reads — importing _catalog.js separately
// from an ESM test can otherwise produce a second instance whose
// override the handler never sees.
module.exports.__catalogTesting__ = require("./_catalog.js").__testing__;
