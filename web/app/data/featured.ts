// Typed adapter for /data/featured.json.
//
// Phase 3 of the hero-rewrite plan extended the file shape: alongside
// the legacy 12-entry rotation `pool[]` it now also writes a 3-entry
// `picks_for_proof_row[]` plus a `proof_row_tier` string. The legacy
// Hero in pages.jsx reads `pool[]`; the new homepage components built
// in Phase 4 read `picks_for_proof_row`.
//
// This module centralises the fetch + shape narrowing so callers don't
// re-implement defensive `Array.isArray` / `typeof === "string"` chains
// at every read site. Same lazy-fetch pattern as data/listings.ts.

import type { DiscoveryTag, MasterCategory, Subcategory } from "./types";

// ── Public types ─────────────────────────────────────────────────────

export type ProofRowTier =
  | "override"
  | "strict"
  | "relaxed_rank"
  | "relaxed_eligibility"
  | "shortfall";

export type ProofRowPick = {
  /** `{source}|{source_id}` — same format as pulpo/featured_listing._key.
   *  Adapter converts the `|` to `-` to match data/listings.ts ids. */
  listing_id: string;
  rank_score: number;
  master_category: MasterCategory | null;
  subcategory: Subcategory | null;
  star_rating: number;
  hero_eligible: boolean;
  card_eligible: boolean;
};

export type FeaturedPoolEntry = {
  listing_id: string;
  rank_score: number;
  hero_photo_quality_score: number | null;
  photos_count: number;
};

export type FeaturedJson = {
  tier: string | null;                       // "elite" | "soft" | "fallback" | "none"
  picked_at: string | null;                  // ISO8601
  expires_at: string | null;                 // ISO8601
  /** Legacy 12-entry rotation. Drives the current Hero. */
  pool: FeaturedPoolEntry[];
  /** New 3-entry proof row. Drives the rewritten homepage proof surface. */
  picks_for_proof_row: ProofRowPick[];
  proof_row_tier: ProofRowTier | null;
};

// ── Internal narrowing helpers ───────────────────────────────────────

const VALID_MASTER: ReadonlySet<MasterCategory> = new Set(["beach", "lake"]);
const VALID_SUB:    ReadonlySet<Subcategory>    = new Set(["homes", "condos", "land"]);
const VALID_TIER:   ReadonlySet<ProofRowTier>   = new Set([
  "override", "strict", "relaxed_rank", "relaxed_eligibility", "shortfall",
]);

function adaptPoolEntry(raw: unknown): FeaturedPoolEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.listing_id !== "string" || r.listing_id.length === 0) return null;
  return {
    listing_id: r.listing_id,
    rank_score: typeof r.rank_score === "number" ? r.rank_score : 0,
    hero_photo_quality_score:
      typeof r.hero_photo_quality_score === "number" ? r.hero_photo_quality_score : null,
    photos_count: typeof r.photos_count === "number" ? r.photos_count : 0,
  };
}

function adaptProofRowPick(raw: unknown): ProofRowPick | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.listing_id !== "string" || r.listing_id.length === 0) return null;
  return {
    listing_id: r.listing_id,
    rank_score: typeof r.rank_score === "number" ? r.rank_score : 0,
    master_category:
      typeof r.master_category === "string" && VALID_MASTER.has(r.master_category as MasterCategory)
        ? (r.master_category as MasterCategory)
        : null,
    subcategory:
      typeof r.subcategory === "string" && VALID_SUB.has(r.subcategory as Subcategory)
        ? (r.subcategory as Subcategory)
        : null,
    star_rating: typeof r.star_rating === "number" ? r.star_rating : 0,
    hero_eligible: r.hero_eligible === true,
    card_eligible: r.card_eligible === true,
  };
}

/** Shape-narrowing adapter. Always returns a FeaturedJson — missing
 *  fields land as their defensive defaults (empty arrays, null tier)
 *  so callers don't need null-guard at every property access. */
export function adaptFeaturedJson(raw: unknown): FeaturedJson {
  if (!raw || typeof raw !== "object") {
    return _empty();
  }
  const r = raw as Record<string, unknown>;
  const pool = Array.isArray(r.pool)
    ? (r.pool.map(adaptPoolEntry).filter((e): e is FeaturedPoolEntry => e !== null))
    : [];
  const picks = Array.isArray(r.picks_for_proof_row)
    ? (r.picks_for_proof_row.map(adaptProofRowPick).filter((p): p is ProofRowPick => p !== null))
    : [];
  const proofTier =
    typeof r.proof_row_tier === "string" && VALID_TIER.has(r.proof_row_tier as ProofRowTier)
      ? (r.proof_row_tier as ProofRowTier)
      : null;
  return {
    tier:                typeof r.tier === "string" ? r.tier : null,
    picked_at:           typeof r.picked_at === "string" ? r.picked_at : null,
    expires_at:          typeof r.expires_at === "string" ? r.expires_at : null,
    pool,
    picks_for_proof_row: picks,
    proof_row_tier:      proofTier,
  };
}

function _empty(): FeaturedJson {
  return {
    tier:                null,
    picked_at:           null,
    expires_at:          null,
    pool:                [],
    picks_for_proof_row: [],
    proof_row_tier:      null,
  };
}

// ── Fetcher ──────────────────────────────────────────────────────────

/** Fetch + adapt /data/featured.json with the standard ~600ms safety
 *  net used everywhere else in the app. Returns null when the file is
 *  unreachable (404 / network failure / timeout) so callers can fall
 *  through to the client-side legacy hero pick.
 *
 *  The 600ms ceiling matches the existing inline fetch in pages.jsx
 *  (Hero is the LCP element on Discover landing — we won't let the
 *  daily-data fetch hold paint past this). */
export async function loadFeaturedJson(timeoutMs = 600): Promise<FeaturedJson | null> {
  const ac = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer = ac ? setTimeout(() => ac.abort(), timeoutMs) : null;
  try {
    // Lazy-import the perf-instrumented fetch so this module doesn't
    // pull telemetry into every component that imports the types.
    const { timedFetch } = await import("../telemetry/perf");
    const res = await timedFetch("featured.json", "/data/featured.json", {
      headers: { Accept: "application/json" },
      ...(ac ? { signal: ac.signal } : {}),
    });
    if (!res.ok) return null;
    const raw = await res.json();
    return adaptFeaturedJson(raw);
  } catch {
    return null;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** Convert featured-pool listing IDs (`source|source_id`) to the
 *  double-underscore form used by data/listings.ts ids today.
 *  PR #244 standardised the ID format on `${source}__${source_id}`
 *  to match what `/api/social/listings` emits (pulpo-social embeds
 *  these ids in IG/FB UTM links — a separator mismatch 404s the
 *  shared listing). Helper was hyphen-form before that change;
 *  Wave-5b updated it when wiring FeaturedDeal to real listings. */
export function featuredIdToListingId(featuredId: string): string {
  return featuredId.replace("|", "__");
}
