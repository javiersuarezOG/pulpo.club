// PR-MC-4 — ACTIVE_COUNTRY contract tests.
//
// The frontend reads VITE_PULPO_ACTIVE_COUNTRY at build time and
// resolves a single CountryManifest for the deployment. These tests
// pin the SV default (no env var set) and the shape of the helpers
// downstream consumers rely on.
//
// Per-country switch tests (e.g. "VITE_PULPO_ACTIVE_COUNTRY=GT
// resolves to GT manifest") aren't possible in vitest without re-
// importing the module mid-test; that's covered indirectly by the
// e2e canary that boots the dev server with a different env var.

import { describe, expect, it } from "vitest";
import { ACTIVE_COUNTRY, ACTIVE_COUNTRY_CODE, countryName, intlLocale } from "./countries";

describe("ACTIVE_COUNTRY default (SV)", () => {
  it("resolves to the SV manifest when env var unset", () => {
    expect(ACTIVE_COUNTRY.code).toBe("SV");
    expect(ACTIVE_COUNTRY.name_en).toBe("El Salvador");
    expect(ACTIVE_COUNTRY.name_es).toBe("El Salvador");
    expect(ACTIVE_COUNTRY.locale_es).toBe("es-SV");
    expect(ACTIVE_COUNTRY.locale_en).toBe("en-US");
    expect(ACTIVE_COUNTRY.currency).toBe("USD");
  });

  it("exposes the SV demonym for prompt-style copy", () => {
    expect(ACTIVE_COUNTRY.name_adjective_en).toBe("Salvadoran");
  });

  it("freezes ACTIVE_COUNTRY so consumers can't mutate it", () => {
    expect(Object.isFrozen(ACTIVE_COUNTRY)).toBe(true);
  });

  it("ACTIVE_COUNTRY_CODE convenience matches .code", () => {
    expect(ACTIVE_COUNTRY_CODE).toBe(ACTIVE_COUNTRY.code);
  });
});

describe("countryName(locale)", () => {
  it("returns Spanish name when locale='es'", () => {
    expect(countryName("es")).toBe(ACTIVE_COUNTRY.name_es);
  });
  it("returns English name when locale='en'", () => {
    expect(countryName("en")).toBe(ACTIVE_COUNTRY.name_en);
  });
});

describe("intlLocale(locale)", () => {
  it("returns the SV BCP-47 tag for 'es'", () => {
    expect(intlLocale("es")).toBe("es-SV");
  });
  it("returns the en-US tag for 'en' (SV deployment uses US English fallback)", () => {
    expect(intlLocale("en")).toBe("en-US");
  });
});
