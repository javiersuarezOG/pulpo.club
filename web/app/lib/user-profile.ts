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

export type UserProfile = {
  // The categories the user wants prioritized — newsletter, future
  // Discover personalization, "alerts for new listings matching",
  // etc. Empty / missing = no preference set; consumers fall back to
  // their unfiltered default.
  preferred_categories?: PreferenceCategoryKey[];

  // Future fields (none in this PR — listed as anchors for the README;
  // remove the comment once one of these actually ships):
  //   budget_range?: { min: number; max: number; currency: "USD" };
  //   preferred_zones?: string[];
  //   notification_quiet_hours?: { start: string; end: string; tz: string };
};

// Safe accessor. Tolerates missing / malformed `profile` blobs (older
// localStorage seeds without the field, hand-edited Clerk metadata).
export function readProfile(user: { profile?: unknown } | null | undefined): UserProfile {
  if (!user || typeof user !== "object") return {};
  const raw = (user as { profile?: unknown }).profile;
  if (!raw || typeof raw !== "object") return {};
  return raw as UserProfile;
}
