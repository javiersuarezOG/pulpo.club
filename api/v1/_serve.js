// api/v1/_serve.js — the pipeline both listing endpoints share.
//
// CommonJS: a TypeScript function cannot reach outside api/ at any
// depth, and this needs the shared core (docs/api-v1.md).
//
// Every step here is the shared core; this file only wires them
// together and injects the two things a serverless function knows that
// the browser does not: where the catalog lives on disk, and which
// country manifest to hand the adapter.
//
//   catalog rows -> adaptListing -> applyFilters -> applyRankCap -> sort
//
// That is the same sequence web/app/pages.jsx runs on every keystroke,
// calling the same functions. If the two ever disagree, one of them
// stopped using shared/ — which is what the parity test checks.

const fs = require("fs");
const path = require("path");

// The shared core, via the CommonJS bridge. A CommonJS entrypoint may
// require across the api/ boundary; a TypeScript one may not, at any
// depth. That is why these handlers are .js.
const {
  adaptListing,
  applyFilters,
  applyRankCap,
  makeDefaultFilters,
  readFilterFromURL,
  buildListingId,
} = require("../_core.js");
const { loadCatalog } = require("./_catalog.js");



/** Sorts v1 exposes. Deliberately a subset of the website's nine: the
 *  others depend on user-adjustable V/L/M weights, which are a web
 *  power feature and would make every response uncacheable. Additive
 *  later if a channel actually needs them. */
const SORTS = ["rank", "price_asc", "price_desc", "newest"];
const DEFAULT_SORT = "rank";

const DEFAULT_LIMIT = 10;
const MAX_LIMIT = 50;
const MAX_OFFSET = 2000;

const comparators = {
  // The catalog arrives pre-sorted by the pipeline's rank_score, but
  // sort explicitly rather than relying on that: adaptListing and the
  // filters both preserve order, yet depending on an upstream invariant
  // nobody restates is how it eventually breaks silently.
  rank: (a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0),
  price_asc: (a, b) => (a.price ?? Infinity) - (b.price ?? Infinity),
  price_desc: (a, b) => (b.price ?? -1) - (a.price ?? -1),
  // Null age sinks to the end: unknown is not "newest". Matches the
  // website's `recent` sorter.
  newest: (a, b) => {
    const av = typeof a.first_seen_date === "number" ? a.first_seen_date : Number.POSITIVE_INFINITY;
    const bv = typeof b.first_seen_date === "number" ? b.first_seen_date : Number.POSITIVE_INFINITY;
    return av - bv;
  },
};

let manifestCache = {};

/**
 * Country manifest for the adapter. Read from pulpo/countries/<cc>.json
 * — the same manifest the pipeline uses — rather than hardcoding a name
 * here, which would also trip scripts/check_country_hardcodes.py.
 *
 * Falls back to the bare code if the manifest is missing from the
 * bundle: a missing display name should degrade one string, not 503 the
 * endpoint. Every catalog row carries its own `country` anyway, so this
 * is only the fallback path.
 */
function countryRef(code) {
  if (manifestCache[code]) return manifestCache[code];
  const candidates = [
    path.join(__dirname, "..", "..", "pulpo", "countries", `${code.toLowerCase()}.json`),
    path.join(process.cwd(), "pulpo", "countries", `${code.toLowerCase()}.json`),
  ];
  for (const p of candidates) {
    try {
      const m = JSON.parse(fs.readFileSync(p, "utf8"));
      if (typeof m?.name_en === "string") {
        manifestCache[code] = { code, name_en: m.name_en };
        return manifestCache[code];
      }
    } catch {
      // next candidate
    }
  }
  return { code, name_en: code };
}

/**
 * Clamp a positive-integer query param, ignoring junk rather than 400ing
 * — a bot sending `limit=abc` should get the default page, not an error.
 *
 * The absent check is explicit and load-bearing: `Number(null)` is 0,
 * not NaN, so a `!Number.isFinite` guard alone silently turns a missing
 * `limit` into `clamp(0)` = 1 and every default request returns a
 * single listing. Caught by the envelope test before it shipped.
 */
function clampInt(raw, fallback, min, max) {
  const first = Array.isArray(raw) ? raw[0] : raw;
  if (first == null || first === "") return fallback;
  const v = Number(first);
  if (!Number.isFinite(v)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(v)));
}

function resolveSort(raw) {
  const v = String(Array.isArray(raw) ? raw[0] : raw ?? "").trim();
  return SORTS.includes(v) ? v : DEFAULT_SORT;
}

/** Adapt every catalog row for a country. */
function adaptAll(rows, code) {
  const ref = countryRef(code);
  return rows.map((r) => adaptListing(r, ref));
}

/**
 * The capability itself: filter + rank + page, entirely via shared/.
 *
 * `query` is a URLSearchParams-compatible string parsed with the SAME
 * codec the website uses for share links, so
 *   /browse?sub=land&pmax=250000  and
 *   /api/v1/listings?sub=land&pmax=250000
 * mean the same thing by construction.
 */
function selectListings(listings, query) {
  const params = new URLSearchParams(query);
  const filters = readFilterFromURL(query, makeDefaultFilters());

  const filtered = applyRankCap(applyFilters(listings, filters), filters.rank_max);
  const sorted = [...filtered].sort(comparators[resolveSort(params.get("sort"))]);

  const limit = clampInt(params.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT);
  const offset = clampInt(params.get("offset"), 0, 0, MAX_OFFSET);

  return {
    // total is the size of the FILTERED set, not the page — a channel
    // needs it to decide whether to offer "more results".
    total: sorted.length,
    listings: sorted.slice(offset, offset + limit),
    limit,
    offset,
  };
}

/** Load + adapt a country's catalog, or null when the data is missing. */
function loadAdapted(code) {
  const catalog = loadCatalog(code);
  if (!catalog) return null;
  return { listings: adaptAll(catalog.rows, code), generatedAt: catalog.generatedAt };
}

/** Absolute URL for a bundle-relative photo path, so a Telegram or MCP
 *  client can fetch the image without knowing our origin. */
function absolutePhoto(url, base) {
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  return `${base.replace(/\/$/, "")}${url.startsWith("/") ? "" : "/"}${url}`;
}

function publicBaseUrl() {
  return (process.env.PULPO_PUBLIC_BASE_URL || "https://pulpo.club").replace(/\/$/, "");
}

/** Project a Listing for the wire: absolute photo URLs + a deep link
 *  back to the website. Bilingual fields pass through untouched — one
 *  cacheable representation, and the channel picks the locale. */
function toWire(l) {
  const base = publicBaseUrl();
  return {
    ...l,
    photos: Array.isArray(l.photos)
      ? l.photos.map((p) =>
          typeof p === "string"
            ? absolutePhoto(p, base)
            : { ...p, url: absolutePhoto(p?.url, base) },
        )
      : l.photos,
    thumbnail_url: absolutePhoto(l.thumbnail_url, base),
    url: `${base}/listing/${encodeURIComponent(l.id)}`,
  };
}

module.exports = {
  SORTS,
  DEFAULT_SORT,
  DEFAULT_LIMIT,
  MAX_LIMIT,
  MAX_OFFSET,
  countryRef,
  clampInt,
  resolveSort,
  adaptAll,
  selectListings,
  loadAdapted,
  absolutePhoto,
  publicBaseUrl,
  toWire,
  buildListingId,
};
