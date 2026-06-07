// Exact-lookup search for /browse. The first iteration intentionally
// avoids fuzzy matching — Pulpo users today reach a specific listing
// by pasting the broker URL, the Pulpo id (`source__source_id`), the
// raw source_id (e.g. `1404`), or a slug fragment from the URL. These
// are exact-substring lookups; fuzzy ranking would actively hurt
// (Fuse.js scoring "1404" against three other listings with "14040"
// in the title is noise).
//
// The matcher is "all tokens must hit some haystack field." Each token
// is a case-insensitive substring; haystack is the union of every
// human-visible identifier on a Listing. Empty / whitespace queries
// match every listing (the search is treated as off).
//
// Fields included (order doesn't matter — substring on the union):
//   id                  — Pulpo composite "<source>__<source_id>"
//   source_id           — raw broker id (paste-from-listing-card)
//   source_label        — pretty broker name ("RE/MAX", "Goodlife")
//   zone_name           — pretty zone label ("Playa El Tunco")
//   province_state      — region label
//   title.en / title.es — both locales so cross-locale search works
//   original_url        — broker URL (with ?referer= etc. still intact)
//
// Capped at 200 chars on the URL-read side. Empty array of tokens
// means no-op match-all. ASCII-folding (Configurable) so that
// "Conchagua" matches "conchaguá" — but kept conservative: we
// lowercase + strip accents only on the haystack/needle as they
// enter the match, not anywhere else in the app.

import type { Listing } from "../data/types";

export function tokenize(query: string | null | undefined): string[] {
  if (!query) return [];
  return foldAscii(query)
    .split(/\s+/)
    .map((tok) => tok.trim())
    .filter(Boolean);
}

export function matchesQuery(
  listing: Listing | null | undefined,
  tokens: string[],
): boolean {
  if (!tokens || tokens.length === 0) return true;
  if (!listing) return false;
  const haystack = buildHaystack(listing);
  for (const tok of tokens) {
    if (!haystack.includes(tok)) return false;
  }
  return true;
}

// Cheap one-shot convenience for call-sites that don't want to
// tokenize manually.
export function matchesQueryString(
  listing: Listing | null | undefined,
  query: string | null | undefined,
): boolean {
  return matchesQuery(listing, tokenize(query));
}

function buildHaystack(listing: Listing): string {
  const parts: Array<string | null | undefined> = [
    listing.id,
    listing.source_id,
    listing.source_label,
    listing.zone_name,
    listing.province_state,
    listing.title?.en,
    listing.title?.es,
    listing.original_url,
  ];
  return foldAscii(parts.filter(Boolean).join(" "));
}

// Lowercase + strip diacritics. We use the same fold on both sides so
// "Conchagua" matches "Conchaguá" and "EL TUNCO" matches "el tunco".
// Anything else we leave alone — numeric ids and URL slugs are
// already ASCII.
// U+0300..U+036F is the Combining Diacritical Marks block. NFD splits
// "é" into "e" + the combining accent, and this regex strips the latter.
const COMBINING_DIACRITICS_RE = /[̀-ͯ]/g;

function foldAscii(s: string): string {
  return s.normalize("NFD").replace(COMBINING_DIACRITICS_RE, "").toLowerCase();
}
