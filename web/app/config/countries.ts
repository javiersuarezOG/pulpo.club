// Frontend twin of pulpo.countries (Python). One JSON manifest per
// country lives at ../config/countries/<cc>.json. The active country is
// selected at build time via VITE_PULPO_ACTIVE_COUNTRY (default "SV"),
// so every deployment renders exactly one country.
//
// PR-MC-4 — replaces the scatter of hardcoded "El Salvador" / "SV"
// strings across web/app/ with a single `ACTIVE_COUNTRY` read. To add a
// country: drop <cc>.json into ./countries/, update the static import
// switch below, and ship a deployment with the new VITE_PULPO_ACTIVE_COUNTRY.
//
// Why a static import switch (not dynamic): Vite's `import()` needs a
// statically analyzable path to tree-shake unused JSON. A literal
// switch on the env var keeps the bundle to the active country's
// payload only — adding GT later means ~6KB more in the GT build, zero
// extra weight in SV.

import svManifest from "./countries/sv.json";
import paManifest from "./countries/pa.json";

export type CountryManifest = {
  code: string;             // ISO-3166-1 alpha-2 (uppercase)
  name_en: string;
  name_es: string;
  name_adjective_en?: string;
  locale_es: string;
  locale_en: string;
  currency: string;
  centroid_lat: number;
  centroid_lng: number;
  // Optional reference sections — present on SV today, may be missing
  // on partial manifests for a new country. Consumers should null-guard.
  zone_tier?: Record<string, string>;
  vacation_zones?: string[];
  coastal_zones?: string[];
  named_beaches?: [string, number, number][];
  airports?: Record<string, { name: string; lat: number; lng: number; operational: boolean }>;
  validation_bounds?: Record<string, Record<string, number[]>>;
  listing_count_floor?: number;
  listing_count_ceiling?: number;
  newsletter_audience_segment?: string;
};

// JSON imports come in as the widest structural type TS can infer
// (e.g. `(string | number)[][]` for the named_beaches tuples), which
// doesn't satisfy our narrower CountryManifest tuple typing. Cast
// through `unknown` so the assertion is explicit. The data is
// statically known to match the schema (parity tests on the Python
// side, byte-identical mirror, JSON Schema validation in CI).
const MANIFESTS: Record<string, CountryManifest> = {
  SV: svManifest as unknown as CountryManifest,
  PA: paManifest as unknown as CountryManifest,
};

// Vite exposes env vars prefixed with VITE_ at build time. The fallback
// to "SV" matches pulpo.countries.active() so local dev + tests behave
// identically without setting the var.
const ACTIVE_CODE: string = (
  (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_PULPO_ACTIVE_COUNTRY
  || "SV"
).toUpperCase();

function resolveActive(): CountryManifest {
  const m = MANIFESTS[ACTIVE_CODE];
  if (!m) {
    // Fall back to SV so a misconfigured deploy doesn't render an empty
    // country chrome. The dev console gets a clear breadcrumb.
    // eslint-disable-next-line no-console
    console.warn(
      `[countries] VITE_PULPO_ACTIVE_COUNTRY="${ACTIVE_CODE}" has no manifest; ` +
      `falling back to SV. Available: ${Object.keys(MANIFESTS).join(",") || "(none)"}`
    );
    return MANIFESTS.SV;
  }
  return m;
}

export const ACTIVE_COUNTRY: Readonly<CountryManifest> = Object.freeze(resolveActive());

/** Return the country's display name in the given locale. Falls back
 *  to English when the locale is unrecognised. */
export function countryName(locale: "en" | "es"): string {
  return locale === "es" ? ACTIVE_COUNTRY.name_es : ACTIVE_COUNTRY.name_en;
}

/** ISO-style locale tag for `Intl.NumberFormat` / `Intl.DateTimeFormat`
 *  in the given UI locale. */
export function intlLocale(locale: "en" | "es"): string {
  return locale === "es" ? ACTIVE_COUNTRY.locale_es : ACTIVE_COUNTRY.locale_en;
}

/** Convenience — the active country's ISO-3166-1 alpha-2 code. */
export const ACTIVE_COUNTRY_CODE: string = ACTIVE_COUNTRY.code;
