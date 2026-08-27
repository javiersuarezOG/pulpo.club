// api/mcp/_tools.js — the three Pulpo capabilities, as MCP tools.
//
// Kept separate from the transport wiring in index.ts so the logic is
// unit-testable without standing up a JSON-RPC server.
//
// Every tool is a thin projection over shared/: the same catalog, the
// same adapter, the same filters and ranking the website runs. An MCP
// client asking "terrenos near El Tunco under $100k" and a user
// dragging the price slider on /browse are answered by the same code.
//
// LLM-facing design notes:
//   * Tool descriptions carry the vocabulary (zone slugs are
//     discoverable via get_market_meta) so the model grounds on real
//     values instead of inventing "el-tunco-beach".
//   * Responses are compact. A full Listing is ~90 fields; dumping 25
//     of those would flood the model's context with photo arrays and
//     score internals it cannot use. Detail is one call away.
//   * Every listing carries its canonical id and a real pulpo.club URL,
//     so the model can cite a link the user can actually open.



const { z } = require("zod");
const { zoneName, parseListingId } = require("../_core.js");
const { loadAdapted, selectListings, publicBaseUrl, absolutePhoto, SORTS } = require("../v1/_serve.js");
const { resolveCountry } = require("../v1/_catalog.js");

const MAX_RESULTS = 25;

/** Compact projection for a result list — enough for the model to
 *  compare options and cite one, without flooding its context. */
function summarize(l) {
  const base = publicBaseUrl();
  return {
    id: l.id,
    title: l.title,
    zone: l.zone_name,
    price_usd: l.price,
    size_m2: l.size_m2,
    price_per_m2: l.price_per_m2,
    category: l.master_category,
    type: l.subcategory,
    score: l.rank_score,
    stars: l.star_rating,
    beachfront: l.beachfront_tier,
    ocean_view: l.has_ocean_view,
    days_listed: l.days_listed,
    url: `${base}/listing/${encodeURIComponent(l.id)}?utm_source=mcp`,
  };
}

/** Fuller projection for a single listing the user drilled into. */
function detail(l) {
  const base = publicBaseUrl();
  return {
    ...summarize(l),
    description: l.description,
    reasons_to_buy: l.usps,
    photos_count: l.photos_count,
    photo: absolutePhoto(l.thumbnail_url, base),
    infrastructure: {
      water: l.has_water,
      power: l.has_power,
      sewage: l.has_sewage,
      road_access: l.road_access_type,
    },
    distances_km: {
      beach: l.dist_beach_km,
      airport: l.dist_airport_km,
      nearest_town: l.dist_nearest_town_km,
    },
    // Price context is what turns a number into a judgement — "is
    // $60k good for El Tunco?" is the question a buyer actually has.
    zone_price_context: {
      vs_zone_median_pct: l.price_vs_zone_pct,
      zone_percentile: l.zone_percentile,
      zone_price_per_m2_min: l.zone_price_per_m2_min,
      zone_price_per_m2_max: l.zone_price_per_m2_max,
      comp_count: l.zone_comp_count,
    },
    readiness_score: l.readiness_score,
    source: l.source_label,
    first_seen_days_ago: l.first_seen_date,
  };
}

/** Turn structured tool args into the website's own query dialect, so
 *  MCP, the website and /api/v1 all resolve a request identically. */
function argsToQuery(args) {
  const p = new URLSearchParams();
  const set = (k, v) => {
    if (v == null || v === "") return;
    p.set(k, Array.isArray(v) ? v.join(",") : String(v));
  };
  // Zones are matched by DISPLAY NAME, not slug: applyFilters compares
  // against l.zone_name ("El Tunco"), which is what the website's own
  // ?zones= share param carries. The model is handed slugs by
  // get_market_meta because those are the stable identifiers, so
  // translate here — otherwise `zones:["el-tunco"]` silently returns
  // zero matches, which is worse than an error because it reads as
  // "there is nothing there".
  //
  // zoneName() is safe for both forms: a known slug maps to its curated
  // name, and anything else Title-Cases to exactly what the adapter
  // produced for zone_name. So a model passing "El Tunco" directly also
  // works.
  set("zones", Array.isArray(args.zones)
    ? args.zones.map((z) => zoneName(String(z)))
    : args.zones == null ? args.zones : zoneName(String(args.zones)));
  set("features", args.features);
  set("infra", args.infra);
  set("status", args.status);
  set("tag", args.tags);
  set("master", args.category);
  set("sub", args.type);
  set("pmin", args.price_min);
  set("pmax", args.price_max);
  set("smin", args.size_min);
  set("smax", args.size_max);
  set("q", args.query);
  set("sort", args.sort);
  // Clamp here, not only in the zod schema. The schema protects real
  // MCP calls, but this function is also called directly (tests, and
  // any future in-process caller), and /api/v1's own cap is 50 — twice
  // what a model should be handed at once. Defense in depth so the MCP
  // cap holds whoever calls.
  const requested = Number(args.limit);
  const limit = Number.isFinite(requested)
    ? Math.min(MAX_RESULTS, Math.max(1, Math.trunc(requested)))
    : 10;
  set("limit", limit);
  set("offset", args.offset ?? 0);
  return p.toString();
}

function searchListings(args) {
  const country = resolveCountry(args.country);
  if (!country) return { ok: false, payload: { error: "unknown_country", supported: ["SV"] } };

  const loaded = loadAdapted(country);
  if (!loaded) return { ok: false, payload: { error: "data_unavailable" } };

  const selected = selectListings(loaded.listings, argsToQuery(args));

  return {
    ok: true,
    payload: {
      total_matching: selected.total,
      returned: selected.listings.length,
      offset: selected.offset,
      // The model should say "of 297 matches, here are 10" rather than
      // implying it saw everything.
      data_as_of: loaded.generatedAt,
      listings: selected.listings.map(summarize),
    },
  };
}

function getListing(args) {
  const id = typeof args.id === "string" ? args.id : "";
  if (!parseListingId(id)) return { ok: false, payload: { error: "invalid_id", id } };

  const country = resolveCountry(args.country);
  if (!country) return { ok: false, payload: { error: "unknown_country", supported: ["SV"] } };

  const loaded = loadAdapted(country);
  if (!loaded) return { ok: false, payload: { error: "data_unavailable" } };

  const found = loaded.listings.find((l) => l.id === id);
  if (!found || found.is_sold || found.is_incomplete) {
    return { ok: false, payload: { error: "not_found", id } };
  }
  return { ok: true, payload: { data_as_of: loaded.generatedAt, listing: detail(found) } };
}

function getMarketMeta(args) {
  const country = resolveCountry(args.country);
  if (!country) return { ok: false, payload: { error: "unknown_country", supported: ["SV"] } };

  const loaded = loadAdapted(country);
  if (!loaded) return { ok: false, payload: { error: "data_unavailable" } };

  const visible = loaded.listings.filter((l) => !l.is_sold && !l.is_incomplete);
  const tally = new Map();
  for (const l of visible) {
    const slug = l.zone ?? null;
    const key = typeof slug === "string" && slug ? slug : null;
    if (!key) continue;
    const hit = tally.get(key) ?? { slug: key, name: zoneName(key), count: 0 };
    hit.count += 1;
    tally.set(key, hit);
  }

  const prices = visible.map((l) => l.price).filter((n) => typeof n === "number");

  return {
    ok: true,
    payload: {
      country,
      data_as_of: loaded.generatedAt,
      total_listings: visible.length,
      // Zones are the vocabulary: the model must pick from these slugs
      // rather than inventing one.
      zones: [...tally.values()].sort((a, b) => b.count - a.count),
      categories: ["beach", "lake"],
      types: ["land", "homes", "condos"],
      discovery_tags: ["top_rated", "under_250k", "gated", "waterfront"],
      features: ["beachfront", "ocean_view", "mountain_view", "flat", "water_body"],
      infrastructure: ["water", "power", "paved", "sewage"],
      sorts: SORTS,
      price_usd: prices.length
        ? { min: Math.min(...prices), max: Math.max(...prices) }
        : null,
    },
  };
}

// ── Tool definitions (schema + description the LLM actually reads) ───

const SEARCH_SCHEMA = {
  query: z.string().optional()
    .describe("Free-text keywords matched against title, zone and broker id. All words must match."),
  category: z.enum(["beach", "lake"]).optional()
    .describe("Broad setting of the property."),
  type: z.enum(["land", "homes", "condos"]).optional()
    .describe("Property type. 'land' means a lot/terreno."),
  zones: z.array(z.string()).optional()
    .describe("Zone SLUGS, e.g. ['el-tunco','el-zonte']. Call get_market_meta first for valid slugs — do not guess."),
  price_min: z.number().optional().describe("Minimum price in USD."),
  price_max: z.number().optional().describe("Maximum price in USD."),
  size_min: z.number().optional().describe("Minimum lot size in square metres."),
  size_max: z.number().optional().describe("Maximum lot size in square metres."),
  features: z.array(z.enum(["beachfront", "ocean_view", "mountain_view", "flat", "water_body"])).optional()
    .describe("Required features. ALL listed must apply."),
  infra: z.array(z.enum(["water", "power", "paved", "sewage"])).optional()
    .describe("Required utilities/access. ALL listed must apply."),
  tags: z.array(z.enum(["top_rated", "under_250k", "gated", "waterfront"])).optional()
    .describe("Curated discovery tags. ALL listed must apply."),
  sort: z.enum(SORTS).optional()
    .describe("Result order. Defaults to 'rank' (Pulpo's own quality+value ranking)."),
  limit: z.number().min(1).max(MAX_RESULTS).optional().describe(`Results per page, max ${MAX_RESULTS}. Default 10.`),
  offset: z.number().min(0).optional().describe("Skip this many results, for paging."),
  country: z.string().optional().describe("ISO country code. Only 'SV' (El Salvador) today."),
};

const GET_LISTING_SCHEMA = {
  id: z.string().describe("Canonical listing id, e.g. 'remax__001461165132', as returned by search_listings."),
  country: z.string().optional(),
};

const META_SCHEMA = {
  country: z.string().optional(),
};

module.exports = {
  MAX_RESULTS,
  summarize,
  detail,
  argsToQuery,
  searchListings,
  getListing,
  getMarketMeta,
  SEARCH_SCHEMA,
  GET_LISTING_SCHEMA,
  META_SCHEMA,
};
