// User profile — the open namespace for "what does this user want."
//
// This is intentionally a dictionary with no upfront schema beyond
// known fields. As we learn what to ask people, fields slot in here
// without a coordinated migration. Existing clients reading a field
// they don't know about should never crash — `readProfile` returns a
// plain object, callers narrow per-field.
//
// Where it lives:
//   - Local cache: `app.user.profile` (mirrored to localStorage via
//     the existing pulpo-user write in app.jsx).
//   - Cross-device (PR-C): Clerk `publicMetadata.profile`.
//
// Newsletter generator + future personalization workers read
// `profile.preferred_categories` — see web/app/lib/categories.ts for
// the vocabulary and README-categories.md for the lifecycle.

import type { PreferenceCategoryKey } from "./categories";

// Cadences the fortnightly newsletter knows how to schedule. The Python
// build_issue module reads this same vocabulary off Clerk publicMetadata
// (see automation/newsletter/build_issue.py) — keep the two in sync.
export const NEWSLETTER_CADENCES = ["fortnight", "monthly", "off"] as const;
export type NewsletterCadence = typeof NEWSLETTER_CADENCES[number];

export const NEWSLETTER_LOCALES = ["en", "es"] as const;
export type NewsletterLocale = typeof NEWSLETTER_LOCALES[number];

export const NEWSLETTER_PROPERTY_TYPES = ["land", "house", "condo"] as const;
export type NewsletterPropertyType = typeof NEWSLETTER_PROPERTY_TYPES[number];

// Filter spec the cron applies to ranked.json to compute a recipient's
// top-N. Every field is optional — missing keys default to "no opinion"
// inside the Python segmenter (web/data/ranked.json is then sliced into
// the broadest fallback cohort).
export type NewsletterPreference = {
  zones?: string[];                       // zone slugs from web/data/ranked.json
  departments?: string[];                 // "La Libertad", "La Paz", …
  property_types?: NewsletterPropertyType[];
  max_price_usd?: number | null;
  min_price_usd?: number | null;
  categories?: PreferenceCategoryKey[];   // subset of categories.ts vocabulary
  locale?: NewsletterLocale;              // overrides browser locale for the email
  cadence?: NewsletterCadence;            // "off" pauses without unsubscribing
};

// ── DiscoverFilter (P2a, 2026-05-29) ─────────────────────────────────
// Unified filter shape persisted from the Discover panel to Clerk
// publicMetadata.profile.discover_filters. Round-trips to the same
// `<FilterPanel>` rendered on /account/newsletter (P2b) and drives the
// weekly newsletter pipeline (P3).
//
// JSON-safe storage form: `Set<string>` axes from the in-memory
// Discover filter become `string[]` here. Use `discoverToStorage` /
// `storageToDiscover` in this module to convert between them.
//
// What's NOT here (intentional, scope decision 2026-05-29):
//   - weights (V/L/M tuning)         — Discover-only "how I read"
//   - score_min                       — Discover-only floor
//   - photos ("all"/"with"/"none")    — Discover-only display toggle
//   - include_incomplete              — Discover-only opt-in
// These stay client-state to avoid Clerk write quota burn on every
// slider tick. See api/clerk/update-profile.js isDiscoverFilter for
// the matching server-side validator.
export const DISCOVER_MASTER_CATEGORIES = ["beach", "lake"] as const;
export type DiscoverMasterCategory = typeof DISCOVER_MASTER_CATEGORIES[number];

export const DISCOVER_SUBCATEGORIES = ["homes", "condos", "land"] as const;
export type DiscoverSubcategory = typeof DISCOVER_SUBCATEGORIES[number];

export type DiscoverFilter = {
  zones?: string[];
  land_types?: string[];
  features?: string[];
  infra?: string[];
  status?: string[];
  discovery_tags?: string[];
  price_min?: number;
  price_max?: number | null;
  size_min?: number;
  readiness?: number;
  rank_max?: number | null;
  master_category?: DiscoverMasterCategory | null;
  subcategory?: DiscoverSubcategory | null;
};

export type UserProfile = {
  // The categories the user wants prioritized — newsletter, future
  // Discover personalization, "alerts for new listings matching",
  // etc. Empty / missing = no preference set; consumers fall back to
  // their unfiltered default.
  preferred_categories?: PreferenceCategoryKey[];

  // Legacy newsletter filter spec (departments / property_types /
  // max_price_usd). P3 retires this in favour of `discover_filters`.
  newsletter?: NewsletterPreference;

  // P2a — unified Discover ↔ /account/newsletter filter state. See
  // DiscoverFilter above + discoverToStorage / storageToDiscover.
  discover_filters?: DiscoverFilter;
};

// Safe accessor. Tolerates missing / malformed `profile` blobs (older
// localStorage seeds without the field, hand-edited Clerk metadata).
export function readProfile(user: { profile?: unknown } | null | undefined): UserProfile {
  if (!user || typeof user !== "object") return {};
  const raw = (user as { profile?: unknown }).profile;
  if (!raw || typeof raw !== "object") return {};
  return raw as UserProfile;
}

// Narrowing accessor for the newsletter block specifically. Always returns
// an object so callers can read with `.zones ?? []` without an extra guard.
export function readNewsletterPreference(
  user: { profile?: unknown } | null | undefined,
): NewsletterPreference {
  const profile = readProfile(user);
  const raw = profile.newsletter;
  if (!raw || typeof raw !== "object") return {};
  return raw;
}

// ── DiscoverFilter accessors + converters (P2a) ──────────────────────

// Narrowing accessor for the discover_filters block. Always returns
// an object so callers can read with `.zones ?? []` without a guard.
export function readDiscoverFilter(
  user: { profile?: unknown } | null | undefined,
): DiscoverFilter {
  const profile = readProfile(user);
  const raw = profile.discover_filters;
  if (!raw || typeof raw !== "object") return {};
  return raw as DiscoverFilter;
}

// BrowsePage's in-memory filter shape (mirrors `makeDefaultFilters()`
// in web/app/pages.jsx). Only the axes that survive Clerk persistence
// are typed here — the four excluded tuning knobs (weights, score_min,
// photos, include_incomplete) stay on BrowsePage's local state and
// are stripped by `discoverToStorage`.
//
// Typed as `unknown`-ish because pages.jsx is JavaScript and its full
// shape isn't statically known to TypeScript callers; the converters
// below validate per-field anyway, so a stray axis just falls through.
export type DiscoverInMemoryFilter = {
  zones?: Set<string>;
  land_types?: Set<string>;
  features?: Set<string>;
  infra?: Set<string>;
  status?: Set<string>;
  discovery_tags?: Set<string>;
  price_min?: number;
  price_max?: number | null;
  size_min?: number;
  readiness?: number;
  rank_max?: number | null;
  master_category?: DiscoverMasterCategory | null;
  subcategory?: DiscoverSubcategory | null;
  // Tuning knobs — present in the in-memory shape but stripped on
  // serialise. Kept here so the type still describes the real value
  // BrowsePage holds.
  weights?: unknown;
  score_min?: number;
  photos?: string;
  include_incomplete?: boolean;
};

function sortedArray(s: Set<string> | undefined): string[] | undefined {
  if (!s || s.size === 0) return undefined;
  // Deterministic ordering so two equivalent filters serialise to the
  // same JSON — keeps storage diffable and the Clerk write a no-op
  // when nothing actually changed.
  return [...s].sort();
}

// Discover (in-memory, Set-backed) → storage (JSON-safe, sorted
// arrays). Empty axes are dropped so the stored blob stays compact and
// the server validator's "missing key = no opinion" path wins over an
// explicit empty array we'd have to defend.
export function discoverToStorage(filter: DiscoverInMemoryFilter): DiscoverFilter {
  const out: DiscoverFilter = {};
  const zones          = sortedArray(filter.zones);
  if (zones)          out.zones = zones;
  const land_types     = sortedArray(filter.land_types);
  if (land_types)     out.land_types = land_types;
  const features       = sortedArray(filter.features);
  if (features)       out.features = features;
  const infra          = sortedArray(filter.infra);
  if (infra)          out.infra = infra;
  const status         = sortedArray(filter.status);
  if (status)         out.status = status;
  const discovery_tags = sortedArray(filter.discovery_tags);
  if (discovery_tags) out.discovery_tags = discovery_tags;
  // Numeric axes — only persist when the user moved them off default.
  // `0` is the default for price_min / size_min / readiness; `null` is
  // the default for price_max / rank_max.
  if (typeof filter.price_min === "number" && filter.price_min > 0) {
    out.price_min = filter.price_min;
  }
  if (filter.price_max != null) {
    out.price_max = filter.price_max;
  }
  if (typeof filter.size_min === "number" && filter.size_min > 0) {
    out.size_min = filter.size_min;
  }
  if (typeof filter.readiness === "number" && filter.readiness > 0) {
    out.readiness = filter.readiness;
  }
  if (filter.rank_max != null) {
    out.rank_max = filter.rank_max;
  }
  // Enums — only when explicitly set.
  if (filter.master_category === "beach" || filter.master_category === "lake") {
    out.master_category = filter.master_category;
  }
  if (filter.subcategory === "homes" || filter.subcategory === "condos" || filter.subcategory === "land") {
    out.subcategory = filter.subcategory;
  }
  return out;
}

// Storage (JSON arrays) → Discover in-memory (Set-backed). Missing
// axes default to empty Set / 0 / null so the returned object is safe
// to spread into `makeDefaultFilters()`'s shape.
//
// Defensively coerces array contents to strings (a hand-edited Clerk
// blob could contain anything) — non-string entries are dropped, not
// kept as-is.
function stringSetFrom(v: unknown): Set<string> {
  if (!Array.isArray(v)) return new Set();
  return new Set(v.filter((x): x is string => typeof x === "string"));
}

export function storageToDiscover(stored: DiscoverFilter): DiscoverInMemoryFilter {
  return {
    zones:          stringSetFrom(stored.zones),
    land_types:     stringSetFrom(stored.land_types),
    features:       stringSetFrom(stored.features),
    infra:          stringSetFrom(stored.infra),
    status:         stringSetFrom(stored.status),
    discovery_tags: stringSetFrom(stored.discovery_tags),
    price_min:      typeof stored.price_min === "number" ? stored.price_min : 0,
    price_max:      stored.price_max == null ? null : Number(stored.price_max),
    size_min:       typeof stored.size_min === "number" ? stored.size_min : 0,
    readiness:      typeof stored.readiness === "number" ? stored.readiness : 0,
    rank_max:       stored.rank_max == null ? null : Number(stored.rank_max),
    master_category: stored.master_category === "beach" || stored.master_category === "lake"
      ? stored.master_category : null,
    subcategory:    stored.subcategory === "homes" || stored.subcategory === "condos" || stored.subcategory === "land"
      ? stored.subcategory : null,
  };
}

// Cheap structural equality on storage-shape blobs. Used by the
// useDiscoverFilter hook to skip Clerk writes when the new filter
// matches what's already persisted (avoids burning quota on a no-op
// toggle round-trip from the URL parser).
export function discoverFilterEqual(a: DiscoverFilter, b: DiscoverFilter): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
