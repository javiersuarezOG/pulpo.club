// api/v1/_catalog.js — reads the listing catalog off the function bundle.
//
// CommonJS because a TypeScript function cannot reach outside api/ at
// any depth (see docs/api-v1.md); these handlers need shared/.
//
// Deliberately NOT in shared/: it touches `fs` and `process`, and
// shared/ is imported by the browser build. The root tsconfig pins
// `types: []`, so a Node global in shared/ fails the web typecheck
// immediately — that is the guardrail working, not an obstacle.
// Everything channel-agnostic (filters, sort, ids, zone names) lives in
// shared/; "get the bytes off this particular disk" is API-side.
//
// ── The PII boundary ────────────────────────────────────────────────
// Two catalog files exist and only one is safe to serve:
//
//   web/data/ranked.json       12MB — carries broker_name / broker_phone
//                              / broker_email. NEVER served publicly.
//   web/data/ranked.list.json  5.8MB — the 73-field allowlisted
//                              projection (_RANKED_LIST_FIELDS in
//                              automation/pipeline_steps.py). Safe.
//
// The website's loader falls back from the slim file to the full one on
// 404. This module deliberately does NOT copy that fallback: a missing
// slim catalog is `null` here and `503 data_unavailable` at the handler,
// because "degrade to serving broker phone numbers" is not a degraded
// mode we want. vercel.json additionally excludes ranked.json from
// these functions' bundles, so the guarantee is structural as well.

const fs = require("fs");
const path = require("path");

/**
 * Countries this API will serve.
 *
 * SV only for now. PA data exists (`ranked.list.PA.json`) but currently
 * carries El Salvador departments on Panamanian rows — serving it would
 * be publishing known-wrong geography. Adding a country here is the one
 * edit needed once its data is trustworthy.
 */
const SUPPORTED_COUNTRIES = ["SV"];

const DEFAULT_COUNTRY = "SV";

/**
 * Resolve and validate a country query param.
 * Returns null for anything unsupported so the handler can 400 rather
 * than silently serving a different country than the caller asked for.
 */
function resolveCountry(raw) {
  if (raw == null || raw === "") return DEFAULT_COUNTRY;
  const value = String(Array.isArray(raw) ? raw[0] : raw).trim().toUpperCase();
  return SUPPORTED_COUNTRIES.includes(value) ? value : null;
}

/**
 * Catalog filename for a country.
 *
 * Mirrors `data_filename()` in pulpo/countries: the code is inserted
 * before the final extension. SV is the exception — it writes the
 * legacy un-suffixed names, and `ranked.list.SV.json` does not exist on
 * disk, so asking for it would 503 the whole API.
 */
function catalogFilename(country) {
  return country === "SV" ? "ranked.list.json" : `ranked.list.${country}.json`;
}

// Per-country, keyed on mtime — the same shape /api/social/listings has
// used in production. Data changes once nightly, so a warm instance
// parses ~6MB of JSON once and then serves from memory. A redeploy or
// a data commit changes the mtime and invalidates naturally.
const cache = new Map();

function dataFileCandidates(filename) {
  return [
    path.join(__dirname, "..", "..", "web", "data", filename),
    path.join(process.cwd(), "web", "data", filename),
  ];
}

function readJson(filename) {
  for (const p of dataFileCandidates(filename)) {
    try {
      const stat = fs.statSync(p);
      return { json: JSON.parse(fs.readFileSync(p, "utf8")), mtimeMs: stat.mtimeMs };
    } catch {
      // Next candidate. Bundle layout differs between local dev
      // (cwd = repo root) and the deployed lambda (__dirname-relative).
    }
  }
  return null;
}

/** Pipeline timestamp for a country, or null. Best-effort: a missing or
 *  malformed last_updated file must not take the catalog down with it. */
function readGeneratedAt(country) {
  const filename = country === "SV" ? "last_updated.json" : `last_updated.${country}.json`;
  const found = readJson(filename);
  const value = found && found.json ? found.json.last_updated : undefined;
  return typeof value === "string" && value ? value : null;
}

/**
 * Load the catalog for a country.
 *
 * Returns null when the file is missing or is not an array — callers
 * must translate that into 503 `data_unavailable`, never into an empty
 * result set. An empty array and "the data did not deploy" look
 * identical to a channel otherwise, and the second one is an incident.
 */
function loadCatalog(country = DEFAULT_COUNTRY) {
  // Test override wins outright. Checked before touching the filesystem
  // so specs behave identically whether or not web/data exists on the
  // machine running them.
  if (overrides.has(country)) return overrides.get(country) ?? null;

  const filename = catalogFilename(country);

  for (const p of dataFileCandidates(filename)) {
    let mtimeMs;
    try {
      mtimeMs = fs.statSync(p).mtimeMs;
    } catch {
      continue;
    }

    const hit = cache.get(country);
    if (hit && hit.mtimeMs === mtimeMs) return hit.catalog;

    try {
      const parsed = JSON.parse(fs.readFileSync(p, "utf8"));
      if (!Array.isArray(parsed)) return null;
      const catalog = {
        rows: parsed,
        generatedAt: readGeneratedAt(country),
        country,
      };
      cache.set(country, { mtimeMs, catalog });
      return catalog;
    } catch {
      return null;
    }
  }

  return null;
}

// Test overrides, consulted ahead of the filesystem. Specs must never
// read web/data: a test bound to real data turns any odd nightly into a
// CI blocker for every unrelated PR (the social-floor precedent).
// `set(country, null)` models "the catalog did not deploy" so the 503
// path is testable too.
const overrides = new Map();

const __testing__ = {
  setCatalog(country, catalog) {
    overrides.set(country, catalog);
  },
  reset() {
    overrides.clear();
    cache.clear();
  },
};

module.exports = {
  SUPPORTED_COUNTRIES,
  DEFAULT_COUNTRY,
  resolveCountry,
  catalogFilename,
  loadCatalog,
  __testing__,
};
