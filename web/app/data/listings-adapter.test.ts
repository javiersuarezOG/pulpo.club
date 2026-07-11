// listings-adapter.test.ts — PR-5 (WS4).
//
// adaptListing() must expose the raw lat/lng coordinates (for the map
// view) and clamp non-numbers to null so map read-sites can guard with
// hasCoords(). The ~0.5% of listings without coordinates must surface
// as null, not 0 or NaN.

import { describe, it, expect } from "vitest";
import { adaptListing, detectListingLang } from "./listings";
import { tr } from "../i18n.jsx";

describe("adaptListing — bilingual honest-slot (i18n leak safety net)", () => {
  it("places a Spanish-only broker title in the .es slot, not .en", () => {
    const out = adaptListing({
      id: "s__1", source: "s", source_id: "1",
      title: "Terreno con vista al mar en El Zonte",
    });
    expect(out.title.es).toBe("Terreno con vista al mar en El Zonte");
    // NOT mislabeled as English
    expect(out.title.en ?? "").toBe("");
    // an EN-locale user falls back to the (only) Spanish string, not blank
    expect(tr(out.title, "en")).toBe("Terreno con vista al mar en El Zonte");
    // an ES-locale user gets the Spanish string
    expect(tr(out.title, "es")).toBe("Terreno con vista al mar en El Zonte");
  });

  it("places an English-only broker title in the .en slot", () => {
    const out = adaptListing({
      id: "s__2", source: "s", source_id: "2",
      title: "Beachfront Home El Sunzal",
    });
    expect(out.title.en).toBe("Beachfront Home El Sunzal");
    expect(out.title.es).toBeUndefined();
  });

  it("honors the enrichment url_language over the heuristic", () => {
    // Ambiguous text, but url_language declares Spanish → .es slot.
    const out = adaptListing({
      id: "s__3", source: "s", source_id: "3",
      title: "Villa 500", url_language: "es",
    });
    expect(out.title.es).toBe("Villa 500");
    expect(out.title.en ?? "").toBe("");
  });

  it("preserves a fully bilingual canonical title", () => {
    const out = adaptListing({
      id: "s__4", source: "s", source_id: "4",
      title_canonical: { en: "Ocean-view lot", es: "Terreno con vista al mar" },
    });
    expect(out.title.en).toBe("Ocean-view lot");
    expect(out.title.es).toBe("Terreno con vista al mar");
  });

  it("falls back to a bilingual Untitled, never a bare English string", () => {
    const out = adaptListing({ id: "s__5", source: "s", source_id: "5" });
    expect(out.title.en).toBe("Untitled");
    expect(out.title.es).toBe("Sin título");
    expect(tr(out.title, "es")).toBe("Sin título");
  });

  it("keeps a Spanish-only USP entry instead of dropping it", () => {
    const out = adaptListing({
      id: "s__6", source: "s", source_id: "6", url_language: "es",
      reasons_to_buy: [{ es: "Vista al mar" }, "A pasos de la playa"],
    });
    expect(out.usps.length).toBe(2);
    expect(out.usps[0].es).toBe("Vista al mar");
    expect(tr(out.usps[1], "en")).toBe("A pasos de la playa");
  });
});

describe("detectListingLang", () => {
  it.each([
    ["Terreno con vista al mar", "es"],
    ["Beachfront Home for Sale", "en"],
    ["Apartamento de lujo frente al mar", "es"],
    ["El Zonte Land", "en"],
    ["Casa", "es"],
    ["", "es"],
  ])("detects %s as %s", (text, expected) => {
    expect(detectListingLang(text)).toBe(expected);
  });
});

describe("adaptListing — lat/lng passthrough (PR-5)", () => {
  it("passes numeric lat/lng through unchanged", () => {
    const out = adaptListing({ id: "x__1", lat: 13.495, lng: -89.383 });
    expect(out.lat).toBe(13.495);
    expect(out.lng).toBe(-89.383);
    expect(out.has_lat_lng).toBe(true);
  });

  it("clamps missing / non-numeric coordinates to null", () => {
    const missing = adaptListing({ id: "x__2" });
    expect(missing.lat).toBeNull();
    expect(missing.lng).toBeNull();
    expect(missing.has_lat_lng).toBe(false);

    const garbage = adaptListing({ id: "x__3", lat: "13.5", lng: null });
    expect(garbage.lat).toBeNull();
    expect(garbage.lng).toBeNull();
    expect(garbage.has_lat_lng).toBe(false);
  });

  it("clamps a half-populated coordinate pair to has_lat_lng=false", () => {
    // lat present but lng missing — not mappable.
    const out = adaptListing({ id: "x__4", lat: 13.5 });
    expect(out.lat).toBe(13.5);
    expect(out.lng).toBeNull();
    expect(out.has_lat_lng).toBe(false);
  });
});
