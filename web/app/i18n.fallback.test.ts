// Unit tests for the i18n.fallback_used leak canary wired into t().
//
// A non-default-locale lookup that falls back to English (or to the raw key)
// is the silent failure mode that shipped to prod twice. t() now fires
// `i18n.fallback_used` once per (locale, key) per session. These tests lock
// that behaviour: fires on a real miss, dedupes, and stays silent for the
// default locale or when a translation exists.
//
// No jsdom — vitest runs in node; we stub a synthetic `window` so the
// browser-only guard in reportI18nFallback() passes (mirrors campaign.test.ts).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Hoisted so the vi.mock factory can reference the spy safely.
const { track } = vi.hoisted(() => ({ track: vi.fn() }));
vi.mock("./telemetry/client", () => ({ track }));

import { t } from "./i18n.jsx";

describe("t() — i18n.fallback_used leak canary", () => {
  beforeEach(() => {
    vi.stubGlobal("window", {});
    track.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("fires once for a missing key in a non-default locale", () => {
    t("zz.canary.missing_a", "es");
    expect(track).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith("i18n.fallback_used", {
      key: "zz.canary.missing_a",
      locale: "es",
    });
  });

  it("dedupes — same key+locale reports only once per session", () => {
    t("zz.canary.missing_b", "es");
    t("zz.canary.missing_b", "es");
    t("zz.canary.missing_b", "es");
    expect(track).toHaveBeenCalledTimes(1);
  });

  it("stays silent for the default locale (en) — English is not a leak", () => {
    t("zz.canary.missing_c", "en");
    expect(track).not.toHaveBeenCalled();
  });

  it("stays silent when the requested locale exists", () => {
    // view.filters is bilingual (en: "Filters", es: "Filtros").
    t("view.filters", "es");
    expect(track).not.toHaveBeenCalled();
  });

  it("does not fire off-browser (no window) even on a miss", () => {
    vi.unstubAllGlobals(); // window back to undefined (node default)
    t("zz.canary.missing_d", "es");
    expect(track).not.toHaveBeenCalled();
  });
});
