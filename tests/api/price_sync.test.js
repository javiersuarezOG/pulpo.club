// Self-test for scripts/check_price_sync.mjs — the price-drift linter
// guarding hidden price surfaces (today: the Python newsletter renderer)
// against the "$19/month stale newsletter" class of drift from
// web/app/lib/pricing.ts.
//
// Per CLAUDE.md's "new CI guardrail" rule: a guardrail must be proven to
// FAIL on known-bad input and PASS on the current tree. Both directions
// live here, plus the comment/allow-marker exemptions that keep the
// linter from flagging documented price history.

import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  SCAN_FILES,
  extractCanonicalAmounts,
  findPriceViolations,
  normalizeAmount,
  main,
} from "../../scripts/check_price_sync.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");

const FAKE_PRICING = `
export const PRICES = {
  eur: { currency: "eur", amount: 4.99, displayString: "€4.99" },
  usd: { currency: "usd", amount: 4.99, displayString: "$4.99" },
};
`;

describe("extractCanonicalAmounts", () => {
  it("collects amounts from both amount: and displayString: rows", () => {
    const amounts = extractCanonicalAmounts(FAKE_PRICING);
    expect(amounts.has("4.99")).toBe(true);
    expect(amounts.size).toBe(1);
  });

  it("extracts from the real pricing.ts", () => {
    const source = fs.readFileSync(path.join(repoRoot, "web/app/lib/pricing.ts"), "utf8");
    const amounts = extractCanonicalAmounts(source);
    expect(amounts.size).toBeGreaterThan(0);
  });
});

describe("normalizeAmount", () => {
  it("treats EU decimal comma and dot as the same amount", () => {
    expect(normalizeAmount("4,99")).toBe("4.99");
    expect(normalizeAmount("4.99")).toBe("4.99");
    expect(normalizeAmount("19")).toBe("19.00");
  });
});

describe("findPriceViolations", () => {
  const canonical = extractCanonicalAmounts(FAKE_PRICING);

  it("FAILS on known-bad input (stale price literal)", () => {
    const bad = `PAYWALL = {"en": "Go Pro — $19/month →"}`;
    const violations = findPriceViolations(bad, canonical);
    expect(violations).toHaveLength(1);
    expect(violations[0].amount).toBe("19.00");
  });

  it("passes on matching literals, dot or comma", () => {
    const good = `PAYWALL = {"en": "Go Pro — $4.99/month →", "es": "Hacete Pro — €4,99/mes →"}`;
    expect(findPriceViolations(good, canonical)).toHaveLength(0);
  });

  it("ignores comment lines (documented price history is allowed)", () => {
    const commented = `# used to be $19/month before the 2026-07 experiment`;
    expect(findPriceViolations(commented, canonical)).toHaveLength(0);
  });

  it("honors the price-sync-allow marker on code lines", () => {
    const allowed = `LEGACY = "$19.00"  # price-sync-allow: historical invoice fixture`;
    expect(findPriceViolations(allowed, canonical)).toHaveLength(0);
  });

  it("does not flag plain numbers without a currency glyph", () => {
    const plain = `TIMEOUT = 4.99  # seconds, not money`;
    expect(findPriceViolations(plain, canonical)).toHaveLength(0);
  });

  it("does not flag listing-price bucket labels ($50k, Under $500k)", () => {
    const buckets = `LABELS = {"en": "Under $50k · Under $100k · Under $500k"}`;
    expect(findPriceViolations(buckets, canonical)).toHaveLength(0);
  });

  it("flags integer per-month forms and dedupes decimal-and-permonth overlap", () => {
    const perMonth = `CTA = {"en": "Go Pro — $19/mo", "es": "Hacete Pro — $4.99/mes"}`;
    const violations = findPriceViolations(perMonth, canonical);
    expect(violations).toHaveLength(1);
    expect(violations[0].amount).toBe("19.00");
  });
});

describe("current tree", () => {
  it("every scanned surface exists", () => {
    for (const rel of SCAN_FILES) {
      expect(fs.existsSync(path.join(repoRoot, rel)), rel).toBe(true);
    }
  });

  it("main() passes on the current tree (run from repo root)", () => {
    const prevCwd = process.cwd();
    try {
      process.chdir(repoRoot);
      expect(main()).toBe(0);
    } finally {
      process.chdir(prevCwd);
    }
  });
});
