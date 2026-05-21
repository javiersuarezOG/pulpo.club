// Category vocabulary — shared across surfaces.
//
// Categories like `beachfront`, `under_50k`, `price_drops` are app-wide
// concepts. They power:
//   - the Discover shelves (`SHELVES` in data.jsx)
//   - the Browse pill rail (`PILLS` in data.jsx)
//   - the account preferences chip selector (this file's consumers)
//   - the future weekly newsletter generator
//   - any future personalization (Discover re-rank, alerts, etc.)
//
// This module is the canonical KEY vocabulary. Display copy for each
// surface lives where the surface lives (data.jsx for pills/shelves;
// i18n.jsx for the preferences UI) — different surfaces want different
// label lengths and tones, so we don't try to share copy here.
//
// See README-categories.md (colocated) for the lifecycle: how to add a
// new category, what changes vs what stays put.

// ── Universe ──────────────────────────────────────────────────────────
//
// Every category key used anywhere in the app. Kept in sync with
// `SHELVES` in web/app/data.jsx — adding a new shelf or pill key
// requires adding it here. The TypeScript narrowing on PREFERENCE_KEYS
// (below) blocks drift: if a preference key isn't in this list, the
// build breaks.
export const CATEGORY_KEYS = [
  "new_this_week",
  "price_drops",
  "off_market",
  "best_documented",
  "beachfront",
  "ocean_view",
  "mountain_view",
  "water_features",
  "flat_buildable",
  "build_ready",
  "commercial",
  "under_50k",
  "under_100k",
  "motivated_sellers",
] as const;
export type CategoryKey = typeof CATEGORY_KEYS[number];
const CATEGORY_KEY_SET = new Set<string>(CATEGORY_KEYS);

// ── User-selectable subset (chip selector in /account/notifications) ─
//
// Not all categories are useful as user preferences. The selector
// surfaces a curated subset chosen for buyer mental model:
//   - "what's new" filters: new_this_week, price_drops
//   - landscape preferences: beachfront, water_features
//   - budget bands: under_50k, under_100k
//
// Ordering here is the chip rendering order in the UI. Reorder freely.
//
// To make a category user-selectable: add the key below + add an
// i18n row `account.notif.pref_cat.<key>` to web/app/i18n.jsx
// (EN + ES). See README-categories.md.
export const PREFERENCE_CATEGORY_KEYS = [
  "new_this_week",
  "price_drops",
  "beachfront",
  "water_features",
  "under_50k",
  "under_100k",
] as const satisfies readonly CategoryKey[];
export type PreferenceCategoryKey = typeof PREFERENCE_CATEGORY_KEYS[number];

// Maps each preference key → its i18n string id. The chip selector
// calls `t(PREFERENCE_CATEGORY_LABEL_KEY[key], locale)` to render.
// Strings themselves live in i18n.jsx so EN/ES versions stay together.
export const PREFERENCE_CATEGORY_LABEL_KEY: Record<PreferenceCategoryKey, string> = {
  new_this_week:  "account.notif.pref_cat.new_this_week",
  price_drops:    "account.notif.pref_cat.price_drops",
  beachfront:     "account.notif.pref_cat.beachfront",
  water_features: "account.notif.pref_cat.water_features",
  under_50k:      "account.notif.pref_cat.under_50k",
  under_100k:     "account.notif.pref_cat.under_100k",
};

// Hard cap on chip selections. The 5th click no-ops + flashes the
// limit hint. To raise the cap, change this number and update the
// (parameterized) i18n string `account.notif.pref_cat.limit_hint`.
export const PREFERENCE_CATEGORIES_MAX = 4;

// ── Sanitization ──────────────────────────────────────────────────────
//
// Filters a stored array to current valid keys + caps at MAX. Use on
// every read — a removed category in stored user data, an older client
// writing a stale key, or a hand-edited Clerk publicMetadata blob
// would otherwise leak unknown values into render.
//
// Returns a fresh array (never mutates input). Preserves insertion
// order; first MAX valid keys win.
export function sanitizePreferredCategories(input: unknown): PreferenceCategoryKey[] {
  if (!Array.isArray(input)) return [];
  const allowed = new Set<string>(PREFERENCE_CATEGORY_KEYS);
  const seen = new Set<string>();
  const out: PreferenceCategoryKey[] = [];
  for (const v of input) {
    if (typeof v !== "string") continue;
    if (!allowed.has(v)) continue;
    if (seen.has(v)) continue;
    seen.add(v);
    out.push(v as PreferenceCategoryKey);
    if (out.length >= PREFERENCE_CATEGORIES_MAX) break;
  }
  return out;
}

// Type guard for the broader category universe — used wherever code
// receives a stringy key and wants to safely narrow before lookup
// (e.g. URL params, telemetry payloads, future Discover personalization).
export function isCategoryKey(value: unknown): value is CategoryKey {
  return typeof value === "string" && CATEGORY_KEY_SET.has(value);
}
