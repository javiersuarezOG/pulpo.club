// Pulpo Discover-homepage shelves — single source of truth.
//
// Why this file exists: the project decided (rewrite plan, post-PR-212)
// to make shelves a flexible variable so the team can iterate on what
// surfaces below the category grid as we learn what visitors engage
// with. Adding a shelf = appending one entry; removing = `enabled:
// false` (preserves the telemetry key) or deleting; editing copy =
// editing in place. No JSX or component code changes needed.
//
// Rewrite Q6 outcome: reduced from the prior 15 shelves to 2 — pure
// "activity signal" that doesn't duplicate the category grid above:
//
//   1. "New this week"            — first_seen_date <= 7
//   2. "Just got more affordable" — is_repriced === true
//
// Both bilingual (en/es) at write time per Q1. Filter predicates are
// pure functions over a Listing → boolean.

import type { Listing } from "../data/types";

export type LocalizedString = { en: string; es: string };

export type ShelfConfig = {
  /** Stable telemetry id — NEVER reuse a retired key for a new shelf,
   *  or PostHog funnels conflate two semantically different surfaces. */
  key: string;
  /** Toggle without deleting. Useful for A/B rollout + quick rollback
   *  while preserving the key so historical PostHog data stays joined. */
  enabled: boolean;
  /** Section header text. Bilingual at write time. */
  label: LocalizedString;
  /** Optional one-line subline under the header. */
  subline?: LocalizedString;
  /** Key into the Icon component (see web/app/components.jsx). */
  icon: string;
  /** Pure filter predicate. Avoid closures over runtime state — if you
   *  need user-aware filtering, pass user as a second arg explicitly. */
  filter: (l: Listing) => boolean;
  /** Optional override of the default render threshold (3). Drop below
   *  when the shelf intentionally surfaces a small set (e.g. premium
   *  picks). Raise above when only a dense rail makes sense. */
  min_items?: number;
};

// Default minimum items for a shelf to render (vs. quietly hiding when
// the filter yields a sparse set). Reduced from 6 to 3 in the rewrite
// so the 2-shelf homepage doesn't flicker on slow data weeks.
export const SHELF_MIN_ITEMS_DEFAULT = 3;

export const SHELVES: readonly ShelfConfig[] = [
  {
    key: "new_this_week",
    enabled: true,
    label:   { en: "New this week",            es: "Nuevas esta semana" },
    subline: {
      en: "Listings that hit the catalog in the last 7 days.",
      es: "Propiedades que entraron al catálogo en los últimos 7 días.",
    },
    icon: "cat_new",
    filter: (l) => l.first_seen_date <= 7,
  },
  {
    key: "price_drops",
    enabled: true,
    label:   { en: "Just got more affordable", es: "Acaban de rebajar el precio" },
    subline: {
      en: "Owners cut their ask — your moment.",
      es: "Los dueños bajaron el precio — este es tu momento.",
    },
    icon: "cat_price_drop",
    filter: (l) => l.is_repriced,
  },
] as const;

/** Iteration helper — drops disabled shelves so callers don't have to. */
export function activeShelves(): readonly ShelfConfig[] {
  return SHELVES.filter((s) => s.enabled);
}

// ── Old shelf keys (retired in this rewrite) ──────────────────────────
// Kept here as a frozen list so the one-time `shelf.config_changed`
// cutover event in app.jsx can ship the before/after diff to PostHog
// without dragging in legacy data.jsx imports. See Step 10b of the
// rewrite plan.
export const RETIRED_SHELF_KEYS: readonly string[] = [
  "off_market",
  "best_documented",
  "beachfront",
  "ocean_view",
  "mountain_view",
  "water_features",
  "flat_buildable",
  "build_ready",
  "commercial",
  "agricultural",
  "under_50k",
  "under_100k",
  "motivated_sellers",
] as const;
