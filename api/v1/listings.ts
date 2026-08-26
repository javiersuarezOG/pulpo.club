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

import { API_VERSION } from "../_core.js";
import { loadAdapted, selectListings, toWire, DEFAULT_LIMIT, MAX_LIMIT } from "./_serve";
import { resolveCountry, SUPPORTED_COUNTRIES } from "./_catalog";
import { makeRateLimiter, ipFromRequest, send429 } from "../_rate_limit.js";
import { methodNotAllowed, logApi, type ApiRequest, type ApiResponse } from "./_http";

const limiter = makeRateLimiter({ windowMs: 60_000, maxAttempts: 60, name: "v1_listings" });

/** The raw query string, however the runtime chose to expose it. */
export function queryString(req: ApiRequest): string {
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

export default function handler(req: ApiRequest, res: ApiResponse) {
  const t0 = Date.now();

  if (req.method !== "GET") return methodNotAllowed(res, "GET");

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) return send429(res, rl, "v1_listings");

  const country = resolveCountry(req.query?.country);
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

export const __testing__ = { DEFAULT_LIMIT, MAX_LIMIT };
