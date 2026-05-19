// Pulpo — consent helpers.
//
// Today this module is small — `openConsentPreferences()` is the only
// export and exists to wire the "Cookie Preferences" footer link to the
// existing ConsentBanner (in pages.jsx). The full ConsentBanner rebuild
// — granular per-category toggles, versioned record, OFF-by-default
// analytics/functional categories — lands in `feat/consent-rebuild`.
//
// Design contract:
//   - `openConsentPreferences()` clears the stored consent decision and
//     dispatches a DOM event the banner listens for. The banner then
//     unhides regardless of region (EU + non-EU users can both review
//     their choice via the footer link).
//   - Telemetry: callers should fire `consent.preferences_opened` with
//     a `source` payload BEFORE calling this helper. This module stays
//     deliberately telemetry-free so it can be called from anywhere
//     without import cycles.

export const CONSENT_PREFERENCES_EVENT = "pulpo:open-consent-preferences";

/**
 * Clears the persisted consent decision and signals the ConsentBanner
 * to re-show. The banner's effect listener then re-enters the
 * undecided state and renders.
 *
 * Safe to call from any component; SSR-safe (no-ops when `window` is
 * undefined).
 */
export function openConsentPreferences(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem("pulpo-consent");
  } catch {
    /* ignore — banner state takes over via the event */
  }
  try {
    window.dispatchEvent(new CustomEvent(CONSENT_PREFERENCES_EVENT));
  } catch {
    /* CustomEvent unsupported in this runtime — ignore */
  }
}
