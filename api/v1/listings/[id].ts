// GET /api/v1/listings/:id — one listing by canonical id.
//
// The id is `<source>__<source_id>` (shared/listing-id.ts), the same
// form that is already in live Instagram, newsletter and share URLs.
//
// Ids arrive from URL paths and from chat messages, and a source_id is
// broker-controlled text, so parseListingId rejects anything outside a
// safe character set rather than sanitising it. A rejected lookup is a
// 404; a sanitised one could be a traversal.
//
// Sold and incomplete listings are NOT served here for the same reason
// they are hidden everywhere else — a channel deep-linking to a sold
// lot wastes the user's trip. Unknown id and hidden listing both return
// 404 rather than leaking which one it was.

import { API_VERSION } from "../../../shared/version";
import { parseListingId } from "../../../shared/listing-id";
import { loadAdapted, toWire } from "../_serve";
import { resolveCountry, SUPPORTED_COUNTRIES } from "../_catalog";
import { makeRateLimiter, ipFromRequest, send429 } from "../../_rate_limit.js";
import { methodNotAllowed, logApi, type ApiRequest, type ApiResponse } from "../_http";

const limiter = makeRateLimiter({ windowMs: 60_000, maxAttempts: 60, name: "v1_listing_detail" });

export default function handler(req: ApiRequest, res: ApiResponse) {
  const t0 = Date.now();

  if (req.method !== "GET") return methodNotAllowed(res, "GET");

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) return send429(res, rl, "v1_listing_detail");

  const rawId = req.query?.id;
  const id = Array.isArray(rawId) ? rawId[0] : rawId;
  if (!parseListingId(id)) {
    logApi("v1_listing_detail", { status: 400, reason: "invalid_id", ms: Date.now() - t0 });
    return res.status(400).json({ error: "invalid_param", param: "id" });
  }

  const country = resolveCountry(req.query?.country);
  if (!country) {
    return res.status(400).json({ error: "unknown_country", supported: SUPPORTED_COUNTRIES });
  }

  const loaded = loadAdapted(country);
  if (!loaded) {
    logApi("v1_listing_detail", { status: 503, country, ms: Date.now() - t0 });
    return res.status(503).json({ error: "data_unavailable" });
  }

  const found = loaded.listings.find((l) => l.id === id);
  if (!found || found.is_sold || found.is_incomplete) {
    // Same 404 for "never existed" and "no longer shown", so the
    // endpoint does not become a probe for which ids we hold.
    logApi("v1_listing_detail", { status: 404, country, ms: Date.now() - t0 });
    return res.status(404).json({ error: "not_found" });
  }

  res.setHeader("Cache-Control", "public, max-age=60, s-maxage=300, stale-while-revalidate=600");
  logApi("v1_listing_detail", { status: 200, country, ms: Date.now() - t0 });

  return res.status(200).json({
    version: API_VERSION,
    country,
    generated_at: loaded.generatedAt,
    data: toWire(found),
  });
}
