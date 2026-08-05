// "Similar listings" selection for the detail page. Pure + deterministic
// so it's unit-testable and stable across re-renders (no Math.random, no
// Date). Runs client-side over the already-loaded catalog — no new data
// payload, no fetch. Feeds ListingCard with surface:"similar" impressions.

import type { Listing } from "../data/types";

// How close two listings are. Higher = more similar. Weights are tuned so
// coarse category dominates, then property kind + zone, then price
// proximity as the tie-breaker within a comparable set.
export function scoreSimilarity(ref: Listing, cand: Listing): number {
  let score = 0;
  // Coarse category (beach / lake) — the strongest "these belong together".
  if (ref.master_category && cand.master_category === ref.master_category) score += 4;
  // Property kind (homes / condos / land); fall back to land_type when the
  // subcategory is null (raw/interior land).
  if (ref.subcategory && cand.subcategory === ref.subcategory) score += 3;
  else if (ref.land_type && cand.land_type === ref.land_type) score += 2;
  // Same zone — local comparability the buyer actually cares about.
  if (ref.zone_name && cand.zone_name === ref.zone_name) score += 3;
  // Price proximity: full 3 within 20%, decaying linearly to 0 at 60%.
  if (ref.price != null && cand.price != null && ref.price > 0) {
    const diff = Math.abs(cand.price - ref.price) / ref.price;
    if (diff <= 0.6) score += 3 * (1 - diff / 0.6);
  }
  return score;
}

// Pick up to `limit` listings most similar to `ref`. A candidate must
// share at least the coarse category OR the zone with the reference so we
// never pad the shelf with something unrelated. Excludes the reference
// itself, incomplete records, and sold listings. Ties break toward the
// better-ranked listing (lower rank number).
export function similarListings(ref: Listing, all: Listing[], limit = 4): Listing[] {
  const candidates = all.filter(
    (l) =>
      l.id !== ref.id &&
      !l.is_incomplete &&
      !l.is_sold &&
      ((ref.master_category != null && l.master_category === ref.master_category) ||
        (!!ref.zone_name && l.zone_name === ref.zone_name)),
  );
  return candidates
    .map((l) => ({ l, s: scoreSimilarity(ref, l) }))
    .sort((a, b) => b.s - a.s || (a.l.rank ?? Number.POSITIVE_INFINITY) - (b.l.rank ?? Number.POSITIVE_INFINITY))
    .slice(0, limit)
    .map((x) => x.l);
}
