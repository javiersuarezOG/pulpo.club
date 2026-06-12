// Free-tier "top 3" view exemption — single source of truth.
//
// The two-state model walls non-paid viewers out of listing detail
// (see app.jsx openListing). The one exception: a Free viewer may open
// the full detail — including the broker/source link — for this week's
// TOP 3 ranked picks. Ranks 4+ stay walled.
//
// The "3" are the highest-rank_score, card-eligible listings — the EXACT
// same set the home hero shows as its unlocked top-3 (HeroV5 FreeTopCard).
// Both the hero and the open-gate import `pickTopRanked` / `freeViewableIds`
// from here so the displayed picks and the openable picks can never drift.

import type { Listing } from "../data/types";

// How many top picks a Free viewer can open in full.
export const FREE_VIEWABLE_COUNT = 3;

// Highest rank_score first, restricted to card-eligible listings with a
// real local thumbnail. Pure + null-safe: an empty/loading dataset
// returns []. (Extracted verbatim from HeroV5's local pickTop so the two
// surfaces share one definition.)
export function pickTopRanked(listings: Listing[] | null | undefined, n: number): Listing[] {
  return (listings || [])
    .filter((l) => l && l.rank_score != null && l.thumbnail_url && l.card_eligible)
    .slice()
    .sort((a, b) => (b.rank_score as number) - (a.rank_score as number))
    .slice(0, n);
}

// The set of listing ids a Free viewer is allowed to open in full.
export function freeViewableIds(listings: Listing[] | null | undefined): Set<string> {
  return new Set(pickTopRanked(listings, FREE_VIEWABLE_COUNT).map((l) => l.id));
}
