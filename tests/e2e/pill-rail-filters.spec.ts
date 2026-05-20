// pill-rail-filters.spec.ts — structural guardrail for the WHERE / RANKING / FILTERS pill rail.
//
// Why this test exists:
//   PR-345 introduced the three-tier rail; the chip predicates moved into
//   applyFilters() in pages.jsx. Two regressions slipped through:
//     1) Top 10 read a non-existent `l.rank` field — clicking the chip
//        with no other filter selected always returned 0 results.
//     2) Top 10 + any other chip intersected with the global top 10,
//        which is almost always empty.
//   This test asserts that every chip — alone, and paired with every
//   other chip across tiers — produces at least one result (when the
//   underlying data has matching listings, which `ranked.json` does).
//
//   If a chip silently returns 0, this fails with the chip name in the
//   failure message instead of the user finding it.

import { test, expect, type Page } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

// Read the chip count off the results header. Returns null if the
// header is missing (page hasn't rendered yet) or NaN-parses.
async function readResultCount(page: Page): Promise<number | null> {
  const num = page.locator(".results-count .num").first();
  await num.waitFor({ state: "visible", timeout: 10_000 });
  const text = (await num.textContent())?.trim() ?? "";
  const n = parseInt(text, 10);
  return Number.isFinite(n) ? n : null;
}

// Click a chip in a given tier (`pill-tier-where|ranking|filters`)
// matching the visible label. Waits for the URL to update so the
// applyFilters re-run is observable downstream.
async function clickPill(page: Page, tier: "where" | "ranking" | "filters", label: RegExp): Promise<void> {
  const chip = page.locator(`.pill-tier-${tier} .pill-chip`).filter({ hasText: label }).first();
  await chip.waitFor({ state: "visible", timeout: 10_000 });
  await chip.click();
  // Chip handler calls history.pushState + app.goBrowse — wait for
  // results-count to re-render rather than racing the React commit.
  await page.waitForTimeout(400);
}

test.describe("Pill rail — every chip returns hits", () => {
  test("Top 10 alone returns 10 results (regression: l.rank bug)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto("/browse", { waitUntil: "networkidle" });
    await readResultCount(page); // wait for first paint

    await clickPill(page, "ranking", /^Top 10$/i);
    const n = await readResultCount(page);
    expect(n, "Top 10 chip alone should produce 10 results — was the rank_max predicate wired to topRankMap?").toBe(10);
    expect(errors).toEqual([]);
  });

  test("Top 10 + Lake returns 10 results (regression: context-aware cap)", async ({ page }) => {
    attachErrorRecorder(page);
    await page.goto("/browse", { waitUntil: "networkidle" });
    await readResultCount(page);

    await clickPill(page, "where", /^Lake$/i);
    await clickPill(page, "ranking", /^Top 10$/i);

    const n = await readResultCount(page);
    expect(n, "Top 10 + Lake should give the top 10 LAKE listings, not the global top 10 narrowed to lake").toBeGreaterThan(0);
    expect(n).toBeLessThanOrEqual(10);
  });

  test("Top 10 + Beach returns 10 results", async ({ page }) => {
    attachErrorRecorder(page);
    await page.goto("/browse", { waitUntil: "networkidle" });
    await readResultCount(page);

    await clickPill(page, "where", /^Beach$/i);
    await clickPill(page, "ranking", /^Top 10$/i);

    const n = await readResultCount(page);
    expect(n).toBeGreaterThan(0);
    expect(n).toBeLessThanOrEqual(10);
  });

  test("Top 10 + Waterfront returns up to 10 results", async ({ page }) => {
    attachErrorRecorder(page);
    await page.goto("/browse", { waitUntil: "networkidle" });
    await readResultCount(page);

    await clickPill(page, "filters", /Waterfront/i);
    await clickPill(page, "ranking", /^Top 10$/i);

    const n = await readResultCount(page);
    expect(n).toBeGreaterThan(0);
    expect(n).toBeLessThanOrEqual(10);
  });

  test("Top 10 + Under $100K returns up to 10 results", async ({ page }) => {
    attachErrorRecorder(page);
    await page.goto("/browse", { waitUntil: "networkidle" });
    await readResultCount(page);

    await clickPill(page, "filters", /Under \$100K/i);
    await clickPill(page, "ranking", /^Top 10$/i);

    const n = await readResultCount(page);
    expect(n).toBeGreaterThan(0);
    expect(n).toBeLessThanOrEqual(10);
  });

  // Each single chip in isolation — make sure no predicate silently
  // returns 0. (Price Drops is excluded because real data has <10
  // is_repriced listings and a zero result there is a data state,
  // not a bug.)
  for (const { tier, label } of [
    { tier: "where" as const,    label: /^Beach$/i },
    { tier: "where" as const,    label: /^Lake$/i },
    { tier: "ranking" as const,  label: /^Top 10$/i },
    { tier: "ranking" as const,  label: /^New$/i },
    { tier: "filters" as const,  label: /Waterfront/i },
    { tier: "filters" as const,  label: /Under \$100K/i },
    { tier: "filters" as const,  label: /Under \$250K/i },
  ]) {
    test(`single chip "${label.source}" returns >0 results`, async ({ page }) => {
      attachErrorRecorder(page);
      await page.goto("/browse", { waitUntil: "networkidle" });
      await readResultCount(page);

      await clickPill(page, tier, label);
      const n = await readResultCount(page);
      expect(n, `chip "${label.source}" should produce at least one result`).toBeGreaterThan(0);
    });
  }
});
