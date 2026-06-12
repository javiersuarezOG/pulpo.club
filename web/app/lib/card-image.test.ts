// Display-gate contract (plan 003): the card-image predicate that
// inventory surfaces (Browse/Saved/map cards via <Photo thumbnail> +
// the Leaflet popup) use to decide whether to render the listing's
// source image or swap in the category fallback. Mirrors the Python
// `is_card_displayable` in pulpo/display_gates.py.

import { describe, it, expect } from "vitest";
import { isCardImageDisplayable } from "./card-image";

describe("isCardImageDisplayable (card display gate)", () => {
  it("passes a card-eligible listing with no text overlay", () => {
    expect(
      isCardImageDisplayable({ card_eligible: true, has_text_overlay: false }),
    ).toBe(true);
  });

  it("passes when has_text_overlay is null (no OCR signal) but card-eligible", () => {
    expect(
      isCardImageDisplayable({ card_eligible: true, has_text_overlay: null }),
    ).toBe(true);
  });

  it("blocks a card-eligible listing flagged as text-overlay (flyer/banner)", () => {
    expect(
      isCardImageDisplayable({ card_eligible: true, has_text_overlay: true }),
    ).toBe(false);
  });

  it("blocks a non-card-eligible listing (logo/too-small)", () => {
    expect(
      isCardImageDisplayable({ card_eligible: false, has_text_overlay: false }),
    ).toBe(false);
  });

  it("blocks when card_eligible is null/missing (photo phase never approved)", () => {
    expect(isCardImageDisplayable({ card_eligible: null })).toBe(false);
    expect(isCardImageDisplayable({})).toBe(false);
  });

  it("blocks null/undefined listings", () => {
    expect(isCardImageDisplayable(null)).toBe(false);
    expect(isCardImageDisplayable(undefined)).toBe(false);
  });
});
