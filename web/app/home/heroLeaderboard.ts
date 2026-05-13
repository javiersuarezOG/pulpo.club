// Pure logic for the hero's dynamic leaderboard. Keeping the cycle
// math out of the React component means:
//   1. Tests can call nextCycle() with deterministic candidates and
//      assert the new board + insertion position without mounting React.
//   2. The component only owns side effects (interval, IO, telemetry).
//   3. A reduced-motion render path uses the same gradeFor() function
//      so the static initial board reads identically to the animated
//      first frame.

/** Sample listings used until the backend wires a real recent-listings
 *  feed. Shape must stay { name, price } so a future real-data swap is
 *  a one-line fixture replacement. */
export type LeaderboardListing = {
  name: string;
  price: number;
};

export const SAMPLE_LISTINGS: ReadonlyArray<LeaderboardListing> = [
  { name: "Las Flores · oceanfront",       price: 845000 },
  { name: "Lago de Coatepeque · 2bd",       price: 324000 },
  { name: "El Tunco · 3bd beach",           price: 615000 },
  { name: "Lago de Suchitlán · land",       price: 198000 },
  { name: "Lago de Ilopango · 4bd",         price: 425000 },
  { name: "Costa del Sol · condo",          price: 720000 },
  { name: "El Sunzal · 2bd cottage",        price: 268000 },
  { name: "Lago de Güija · 3bd",            price: 389000 },
  { name: "Playa El Zonte · loft",          price: 152000 },
  { name: "Bahía de Jiquilisco · lot",      price: 487000 },
  { name: "Punta Roca · cabana",            price: 295000 },
  { name: "Lago de Olomega · land",         price: 118000 },
];

/** Initial widths (percentage 0-100) for the 10-row leaderboard. The
 *  spread runs A+ at position 1 down to C at position 10 — never the
 *  flat "all A" look that read as decorative-only in v2. */
export const INITIAL_WIDTHS: ReadonlyArray<number> = [
  94, 87, 81, 73, 68, 61, 55, 48, 42, 36,
];

export type Grade = "A+" | "A" | "A-" | "B+" | "B" | "B-" | "C+" | "C" | "C-";

/** Width-to-grade mapping per the v3 spec table. Inclusive lower bounds. */
export function gradeFor(width: number): Grade {
  if (width >= 92) return "A+";
  if (width >= 82) return "A";
  if (width >= 74) return "A-";
  if (width >= 66) return "B+";
  if (width >= 58) return "B";
  if (width >= 50) return "B-";
  if (width >= 42) return "C+";
  if (width >= 34) return "C";
  return "C-";
}

/** Tone bucket for CSS class selection. Mirrors the spec's three
 *  bar-color tiers (forest-deep / forest-mid / forest-soft / muted). */
export type BarTone = "deep" | "mid" | "soft" | "muted";
export function toneFor(width: number): BarTone {
  if (width >= 82) return "deep";    // A+, A
  if (width >= 66) return "mid";     // A-, B+
  if (width >= 50) return "soft";    // B, B-
  return "muted";                    // C+, C, C-
}

/** Slug a listing name → a stable id-shaped string for telemetry. The
 *  shape mirrors what the eventual real-listing id will look like.
 *  Pure function so tests can pin the slugger contract. */
export function slugifyListing(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFD")
    // strip combining marks (accents)
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export type CycleResult = {
  /** The new widths array after the candidate's insertion. Always
   *  exactly 10 entries. */
  widths: number[];
  /** 1-based position where the candidate landed (1 = top), or null if
   *  the candidate's score didn't beat any existing entry. */
  insertedAt: number | null;
  /** The listing that's now in the Just In pill — either the inserted
   *  candidate (if it made the board) or the candidate itself with an
   *  off-the-board flag (so the pill still updates even on misses). */
  pillListing: LeaderboardListing;
  pillWidth: number;
  pillGrade: Grade;
};

/** Compute the next cycle's state. Pure function — no globals, no DOM,
 *  no telemetry. Pass in the current widths + a candidate and the
 *  RESULT tells the renderer what to swap. */
export function nextCycle(
  currentWidths: ReadonlyArray<number>,
  candidate: { listing: LeaderboardListing; width: number },
): CycleResult {
  const widths = currentWidths.slice();
  // Find the FIRST position (0-indexed) whose width is < candidate.
  // That's where we'd insert to keep the array descending. If every
  // entry is >= candidate, the candidate is "off the board".
  let insertIdx = -1;
  for (let i = 0; i < widths.length; i += 1) {
    if (candidate.width > widths[i]) { insertIdx = i; break; }
  }

  if (insertIdx === -1) {
    return {
      widths,
      insertedAt: null,
      pillListing: candidate.listing,
      pillWidth: candidate.width,
      pillGrade: gradeFor(candidate.width),
    };
  }

  widths.splice(insertIdx, 0, candidate.width);
  widths.pop(); // drop the last entry so we stay at 10

  return {
    widths,
    insertedAt: insertIdx + 1,
    pillListing: candidate.listing,
    pillWidth: candidate.width,
    pillGrade: gradeFor(candidate.width),
  };
}

/** Generate a random candidate from the sample fixture. Width sits in
 *  the realistic 30–95 range so cycles produce a mix of inserts and
 *  off-the-board entries (a leaderboard that always inserts at #1 is
 *  obviously fake). Two args (listings, rand) so tests can pin both. */
export function randomCandidate(
  listings: ReadonlyArray<LeaderboardListing> = SAMPLE_LISTINGS,
  rand: () => number = Math.random,
): { listing: LeaderboardListing; width: number } {
  const listing = listings[Math.floor(rand() * listings.length)];
  const width = Math.round(30 + rand() * 65); // 30–95
  return { listing, width };
}
