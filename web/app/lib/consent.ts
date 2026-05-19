// Pulpo — consent helpers.
//
// Implements the 9-point ConsentBanner technical contract from
// `legal_documents/03-cookie-policy.md` (mirrors PDF §3.2):
//
//   1. Banner fires BEFORE any analytics/functional script loads.
//   2. Default = strictly-necessary only.
//   3. Accept All + Decline All buttons visually equal weight.
//   4. Granular toggles per category (analytics + functional).
//   5. Consent record persisted to localStorage as
//        consent_v = { v, ts, accepted: [...] }
//   6. On Decline All: do NOT initialise PostHog, Mapbox session,
//      or Resend tracking pixel.
//   7. On Accept All: initialise all category scripts.
//   8. Footer "Cookie Preferences" link re-opens the banner (already
//      shipped in #322 via `openConsentPreferences()`).
//   9. Consent record carries a version tied to the cookie-policy
//      version, so a material policy change can re-ask consent.
//
// Migration: previous releases stored a single string at
// localStorage.pulpo-consent ∈ {"granted","declined",""}. Module
// import runs `migrateLegacyConsent()` once which translates the old
// value into the new shape and removes the legacy key.

export type ConsentCategory =
  | "strictly_necessary"
  | "analytics"
  | "functional";

export const ALL_CATEGORIES: readonly ConsentCategory[] = [
  "strictly_necessary",
  "analytics",
  "functional",
] as const;

// Categories the user can toggle. Strictly necessary is always on.
export const OPTIONAL_CATEGORIES: readonly ConsentCategory[] = [
  "analytics",
  "functional",
] as const;

/** Bump on every material change to legal_documents/03-cookie-policy.md
 *  (new vendor, new cookie category, expanded purpose). Existing users
 *  with a lower-version record see the banner again on next visit. */
export const CONSENT_POLICY_VERSION = 1;

export const CONSENT_STORAGE_KEY = "consent_v";
const LEGACY_STORAGE_KEY = "pulpo-consent";

export const CONSENT_PREFERENCES_EVENT = "pulpo:open-consent-preferences";
export const CONSENT_DECISION_EVENT = "pulpo:consent-decision";

export interface ConsentRecord {
  /** Schema version of this record — matches CONSENT_POLICY_VERSION
   *  at the time the user decided. */
  v: number;
  /** ms-since-epoch timestamp of the decision. */
  ts: number;
  /** Categories the user accepted. Always includes strictly_necessary. */
  accepted: ConsentCategory[];
}

function isConsentRecord(x: unknown): x is ConsentRecord {
  if (!x || typeof x !== "object") return false;
  const r = x as Record<string, unknown>;
  return (
    typeof r.v === "number" &&
    typeof r.ts === "number" &&
    Array.isArray(r.accepted) &&
    r.accepted.every((c) => typeof c === "string")
  );
}

/**
 * Reads the persisted consent record. Returns null when:
 *   - localStorage is unavailable (SSR)
 *   - no record on file
 *   - the record's version is older than CONSENT_POLICY_VERSION
 *     (treat as undecided so the banner re-shows on policy change)
 */
export function readConsent(): ConsentRecord | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(CONSENT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!isConsentRecord(parsed)) return null;
    if (parsed.v < CONSENT_POLICY_VERSION) return null;
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Writes a new consent record. `accepted` may be passed without
 * "strictly_necessary" — this function will dedupe + ensure it's
 * always included.
 */
export function writeConsent(accepted: ConsentCategory[]): ConsentRecord {
  const dedup = new Set<ConsentCategory>(["strictly_necessary"]);
  for (const c of accepted) {
    if (ALL_CATEGORIES.includes(c)) dedup.add(c);
  }
  const record: ConsentRecord = {
    v: CONSENT_POLICY_VERSION,
    ts: Date.now(),
    accepted: Array.from(dedup),
  };
  try {
    if (typeof window !== "undefined") {
      localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(record));
    }
  } catch {
    /* storage quota / private mode — ignore */
  }
  try {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent(CONSENT_DECISION_EVENT, { detail: record }));
    }
  } catch {
    /* CustomEvent unsupported — ignore */
  }
  return record;
}

/**
 * True when the user has affirmatively accepted the given category.
 * Returns FALSE for the "undecided" state — the contract is opt-in.
 * `strictly_necessary` always returns true.
 */
export function hasConsented(cat: ConsentCategory): boolean {
  if (cat === "strictly_necessary") return true;
  const r = readConsent();
  if (!r) return false;
  return r.accepted.includes(cat);
}

/**
 * Clears the persisted consent record entirely. Used by
 * `openConsentPreferences()` so the banner re-renders in its
 * undecided state.
 */
export function clearConsent(): void {
  if (typeof window === "undefined") return;
  try { localStorage.removeItem(CONSENT_STORAGE_KEY); } catch { /* ignore */ }
}

/**
 * Clears the persisted consent decision and signals the ConsentBanner
 * to re-show. Footer's "Cookie Preferences" button calls this.
 */
export function openConsentPreferences(): void {
  if (typeof window === "undefined") return;
  clearConsent();
  try {
    window.dispatchEvent(new CustomEvent(CONSENT_PREFERENCES_EVENT));
  } catch {
    /* CustomEvent unsupported — ignore */
  }
}

/**
 * One-shot migration from the old single-string `pulpo-consent` key
 * to the new versioned record at `consent_v`. Runs on module import.
 *
 *   "granted"  → accept all optional categories (analytics + functional)
 *   "declined" → strictly_necessary only
 *   anything else → no migration; banner will re-ask
 *
 * After migration the legacy key is deleted so we don't keep two
 * shadow copies of the same decision.
 */
export function migrateLegacyConsent(): void {
  if (typeof window === "undefined") return;
  try {
    if (localStorage.getItem(CONSENT_STORAGE_KEY)) return;
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!legacy) return;
    if (legacy === "granted") {
      writeConsent(["analytics", "functional"]);
    } else if (legacy === "declined") {
      writeConsent([]); // strictly_necessary only (added implicitly)
    }
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    /* localStorage unavailable — banner will re-ask */
  }
}

// Run migration on first import — idempotent + cheap.
migrateLegacyConsent();
