// shared/listing-id.ts — the canonical listing identity.
//
// Listings have no `id` field in the pipeline's output; identity is the
// (source, source_id) pair, joined at the consumer. Three join formats
// currently exist in the repo:
//
//   source__source_id   web/app/data/listings.ts, /api/social/listings,
//                       newsletter favorites index           <- canonical
//   source|source_id    web/data/featured.json
//   source-source_id    automation/sitemap.py
//
// The double-underscore form wins because it is already baked into
// live URLs — Instagram/Facebook UTM links, newsletter deep links, and
// every `/listing/<id>` the website has ever emitted. Changing it would
// 404 links already in the wild.
//
// The other two are pre-existing drift, tracked separately. This module
// is the one implementation; new consumers import it rather than
// re-deriving the join, which is how the drift happened in the first
// place.

/** Separator between source and source_id. Load-bearing: it is in live URLs. */
export const ID_SEPARATOR = "__";

/**
 * Characters allowed in an id we are willing to look up.
 *
 * Mirrors `SAFE_LISTING_ID_RE` in web/app/lib/url-routing.ts. Ids reach
 * this code from URL path segments and chat messages, and a source_id
 * is broker-controlled text, so anything outside this set is rejected
 * rather than sanitized — a rejected lookup is a 404, a sanitized one
 * could be a path traversal.
 */
const SAFE_ID_RE = /^[A-Za-z0-9._-]+$/;

export interface ListingIdParts {
  source: string;
  sourceId: string;
}

/**
 * Join a (source, source_id) pair into the canonical id.
 * Returns null when either half is missing or unsafe, so callers can
 * skip the row instead of minting a malformed id.
 */
export function buildListingId(
  source: unknown,
  sourceId: unknown,
): string | null {
  if (typeof source !== "string" || typeof sourceId !== "string") return null;
  const s = source.trim();
  const sid = sourceId.trim();
  if (!s || !sid) return null;
  if (!SAFE_ID_RE.test(s) || !SAFE_ID_RE.test(sid)) return null;
  return `${s}${ID_SEPARATOR}${sid}`;
}

/**
 * Split a canonical id back into its parts.
 *
 * Splits on the FIRST separator: source slugs never contain `__`, but a
 * broker-supplied source_id might, and the source is the half we must
 * recover exactly.
 */
export function parseListingId(id: unknown): ListingIdParts | null {
  if (typeof id !== "string") return null;
  const trimmed = id.trim();
  if (!trimmed || trimmed.length > 200) return null;

  const at = trimmed.indexOf(ID_SEPARATOR);
  if (at <= 0) return null;

  const source = trimmed.slice(0, at);
  const sourceId = trimmed.slice(at + ID_SEPARATOR.length);
  if (!source || !sourceId) return null;
  if (!SAFE_ID_RE.test(source) || !SAFE_ID_RE.test(sourceId)) return null;

  return { source, sourceId };
}

/** True when `id` is a well-formed canonical listing id. */
export function isListingId(id: unknown): boolean {
  return parseListingId(id) !== null;
}
