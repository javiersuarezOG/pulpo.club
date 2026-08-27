// GET /api/v1/listings — ranked, filtered, paginated listings.
//
// The capability every channel is built on. All of the actual logic —
// adapting pipeline rows, filtering, capping, ranking — comes from
// shared/, the same modules web/app/pages.jsx calls on every keystroke.
// This file is HTTP plumbing.
//
// QUERY DIALECT
// Params are parsed with the website's own share-link codec
// (shared/engine/params.ts), so these are the same request:
//   /browse?sub=land&pmax=250000&features=ocean_view
//   /api/v1/listings?sub=land&pmax=250000&features=ocean_view
// Full key list is in docs/api-v1.md. Plus: sort, limit, offset, country.
//
// Unknown params are ignored and malformed numbers fall back to
// defaults rather than 400ing — a bot sending limit=abc should get the
// first page, not an error it has no way to explain to a user.
// `country` is the exception: silently serving a different country than
// asked for would be a lie, so that is a hard 400.
//
// Cache: public, max-age=60, s-maxage=300. The data changes once
// nightly, so the CDN serves nearly every request and origin cost stays
// near zero however much channel traffic arrives.



// CommonJS, not TypeScript: a .ts function cannot reach outside api/ at
// any depth, and these need the shared core (docs/api-v1.md).
const { API_VERSION } = require("../_core.js");
const { loadAdapted, selectListings, toWire, DEFAULT_LIMIT, MAX_LIMIT } = require("./_serve.js");
const { resolveCountry, SUPPORTED_COUNTRIES } = require("./_catalog.js");
const { makeRateLimiter, ipFromRequest, send429 } = require("../_rate_limit.js");
const { methodNotAllowed, logApi } = require("./_http.js");

const limiter = makeRateLimiter({ windowMs: 60_000, maxAttempts: 60, name: "v1_listings" });

/** The raw query string, however the runtime chose to expose it. */
function queryString(req) {
  const fromUrl = typeof req.url === "string" ? req.url.split("?")[1] : "";
  if (fromUrl) return fromUrl;
  const q = req.query;
  if (!q) return "";
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (Array.isArray(v)) v.forEach((one) => params.append(k, one));
    else if (v != null) params.append(k, String(v));
  }
  return params.toString();
}

function handler(req, res) {
  const t0 = Date.now();

  if (req.method !== "GET") return methodNotAllowed(res, "GET");

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) return send429(res, rl, "v1_listings");

  const country = resolveCountry(req.query && req.query.country);
  if (!country) {
    logApi("v1_listings", { status: 400, reason: "unknown_country", ms: Date.now() - t0 });
    return res.status(400).json({ error: "unknown_country", supported: SUPPORTED_COUNTRIES });
  }

  const loaded = loadAdapted(country);
  if (!loaded) {
    // Never an empty page: "no matches" and "the data did not deploy"
    // are indistinguishable to a channel, and only one is an incident.
    logApi("v1_listings", { status: 503, country, ms: Date.now() - t0 });
    return res.status(503).json({ error: "data_unavailable" });
  }

  const selected = selectListings(loaded.listings, queryString(req));

  res.setHeader("Cache-Control", "public, max-age=60, s-maxage=300, stale-while-revalidate=600");
  logApi("v1_listings", {
    status: 200, country, total: selected.total,
    returned: selected.listings.length, ms: Date.now() - t0,
  });

  return res.status(200).json({
    version: API_VERSION,
    country,
    generated_at: loaded.generatedAt,
    total: selected.total,
    limit: selected.limit,
    offset: selected.offset,
    data: selected.listings.map(toWire),
  });
}

module.exports = handler;
module.exports.queryString = queryString;
module.exports.__testing__ = { DEFAULT_LIMIT, MAX_LIMIT };

// Test seam. Re-exported from the handler so specs mutate the SAME
// module instance the handler reads — importing _catalog.js separately
// from an ESM test can otherwise produce a second instance whose
// override the handler never sees.
module.exports.__catalogTesting__ = require("./_catalog.js").__testing__;
