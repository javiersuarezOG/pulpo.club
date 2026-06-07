// Derives the location-precision display tier for a listing from its
// `geocoding_source` and `geocoding_confidence`. The pipeline emits both
// fields on `ranked.json` (see automation/llm_enrichment_schema.py and
// generate_ranked_schema.py) but the FE was historically blind to them
// — so a zone-inferred LLM-guessed lat/lng rendered identically to a
// broker-published precise coordinate. Listings would plot a map pin
// hundreds of metres off and the user had no signal it was a guess.
//
// Tiers:
//   "precise"     — `extracted`: the broker explicitly published the
//                    coordinate (parsed from their structured payload).
//                    Today this is ~0.2% of the SV corpus (4/1912 at
//                    last count) but is the strongest possible signal.
//   "approximate" — `estimated` (DeepSeek inferred) or `nominatim`
//                    (OSM fallback). Both are zone- or
//                    landmark-anchored. Users planning a visit need
//                    to know to confirm the address.
//   "unknown"     — no geocoding ran at all (`null`). The FE typically
//                    suppresses the note entirely in this case so the
//                    surface doesn't lie about precision it doesn't have.
//
// Pure function for vitest. The React presentation lives in
// components.jsx's LocationPrecisionNote — keep that thin.

import type { Listing } from "../data/types";

export type LocationPrecisionTier = "precise" | "approximate" | "unknown";

type ListingPrecisionFields = Pick<
  Listing,
  "geocoding_source" | "geocoding_confidence" | "has_lat_lng"
>;

export function deriveLocationPrecision(
  listing: ListingPrecisionFields | null | undefined,
): LocationPrecisionTier {
  if (!listing) return "unknown";
  const source = listing.geocoding_source ?? null;
  if (source === "extracted") return "precise";
  if (source === "estimated" || source === "nominatim") return "approximate";
  // No geocoding ran. Don't claim precision we don't have.
  return "unknown";
}
