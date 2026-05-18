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

export type UserProfile = {
  // The categories the user wants prioritized — newsletter, future
  // Discover personalization, "alerts for new listings matching",
  // etc. Empty / missing = no preference set; consumers fall back to
  // their unfiltered default.
  preferred_categories?: PreferenceCategoryKey[];

  // Newsletter-specific filter spec. Persisted to Clerk publicMetadata.profile.newsletter
  // and read by the fortnightly cron (see api/clerk/update-profile.js for
  // the matching server-side validator, and automation/newsletter/build_issue.py
  // for the Python consumer).
  newsletter?: NewsletterPreference;
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
