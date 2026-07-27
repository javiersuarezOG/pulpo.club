// Unit tests for the Pulpo Pro price source of truth. Guards two things:
//   1. The displayed amount stays in sync across currencies (a price
//      experiment is a single edit to PRICES — this asserts it landed).
//   2. priceDisplay() applies the ES decimal-comma to EUR only, so the
//      legal copy that derives from it renders "€X,XX" in Spanish but keeps
//      "$X.XX" for USD in both locales.

import { describe, it, expect } from "vitest";
import { PRICES, priceDisplay, priceForCountry } from "./pricing";

describe("PRICES source of truth", () => {
  it("EUR and USD carry the same amount + matching displayString", () => {
    expect(PRICES.eur.amount).toBe(4.99);
    expect(PRICES.usd.amount).toBe(4.99);
    expect(PRICES.eur.displayString).toBe("€4.99");
    expect(PRICES.usd.displayString).toBe("$4.99");
  });
});

describe("priceDisplay", () => {
  it("EUR uses the ES decimal-comma in Spanish", () => {
    expect(priceDisplay("eur", "es")).toBe("€4,99");
  });
  it("EUR uses the dot in English (and by default)", () => {
    expect(priceDisplay("eur", "en")).toBe("€4.99");
    expect(priceDisplay("eur")).toBe("€4.99");
  });
  it("USD keeps the dot in both locales", () => {
    expect(priceDisplay("usd", "es")).toBe("$4.99");
    expect(priceDisplay("usd", "en")).toBe("$4.99");
  });
});

describe("priceForCountry", () => {
  it("EU country → EUR, everywhere else → USD, unknown → USD", () => {
    expect(priceForCountry("ES").currency).toBe("eur");
    expect(priceForCountry("DE").currency).toBe("eur");
    expect(priceForCountry("SV").currency).toBe("usd");
    expect(priceForCountry("US").currency).toBe("usd");
    expect(priceForCountry(null).currency).toBe("usd");
    expect(priceForCountry("zz").currency).toBe("usd");
  });
});
