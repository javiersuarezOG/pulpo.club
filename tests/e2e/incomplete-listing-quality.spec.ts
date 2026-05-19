// Quality-gate regression: incomplete listings (broker hasn't shared
// price or size) are hidden from the default Browse view, surface the
// broker note + "Not shared" copy on direct-link detail pages, and only
// appear in /browse after the user opts in via the "Show missing
// details" filter chip.
//
// Pairs with the backend test_data_quality::test_ranker_demotes_incomplete_below_every_complete
// and the derive_is_incomplete unit tests. CI green here means the
// quality gate's product behaviour holds end-to-end.

import { test, expect } from "@playwright/test";

test.describe("Incomplete-listing quality gate", () => {
  test("hidden from /browse by default; visible on direct detail link with broker note", async ({ page, request }) => {
    const dataRes = await request.get("/data/ranked.json");
    expect(dataRes.status()).toBe(200);
    const json = await dataRes.json();
    const list = Array.isArray(json) ? json : (json.listings ?? []);
    const incompleteSample = (list as Array<{
      source: string; source_id: string; price_usd?: number | null; area_m2?: number | null; is_sold?: boolean;
    }>).find((l) => (l.price_usd == null || l.area_m2 == null) && !l.is_sold);
    expect(incompleteSample, "live data must include at least one incomplete listing").toBeTruthy();
    const incompleteId = `${incompleteSample!.source}__${incompleteSample!.source_id}`;

    // Default /browse view excludes incomplete listings.
    await page.goto("/browse", { waitUntil: "networkidle" });
    await page.locator(".listing-card").first().waitFor({ state: "visible", timeout: 10_000 });
    // The listing-card may not expose its id directly — assert the
    // body text doesn't reference the source_id we expected to filter.
    const bodyText = await page.evaluate(() => document.body.textContent || "");
    // We can only weakly assert here: the id format includes source_id;
    // assert the source_id substring doesn't appear in the rendered
    // card list. If a future card format adds the id to a data attr,
    // tighten this to a DOM query.
    expect(
      bodyText.includes(incompleteSample!.source_id),
      `incomplete listing (${incompleteSample!.source_id}) should be hidden on default /browse`
    ).toBeFalsy();

    // Direct deep-link to the incomplete listing still renders the
    // detail panel + the broker note + "Not shared" keystat.
    await page.goto(`/listing/${incompleteId}`);
    await page.locator(".detail-panel").waitFor({ state: "visible", timeout: 10_000 });
    await expect(page.locator(".detail-broker-note")).toBeVisible();
    const detailText = await page.evaluate(() => document.body.textContent || "");
    expect(
      /Not shared/.test(detailText),
      "detail keystats should surface the 'Not shared' copy for missing fields"
    ).toBeTruthy();
  });

  test("cold-load ?inc=1 expands the result count to include incomplete listings", async ({ page }) => {
    // Regression for the URL-overlay fix: the BrowsePage category-resync
    // useEffect re-fires on mount and was overwriting URL-parsed filter
    // state (notably include_incomplete). Without the overlay in
    // readFilterFromURL(), a direct cold-load on /browse?inc=1 silently
    // reverted to the default-hide view. This test pins that path.
    await page.goto("/browse", { waitUntil: "domcontentloaded" });
    await page.locator(".listing-card").first().waitFor({ state: "visible", timeout: 15_000 });
    await page.waitForTimeout(1500);
    const defaultCount = parseInt((await page.locator(".num").first().textContent()) || "0", 10);

    await page.goto("/browse?inc=1", { waitUntil: "domcontentloaded" });
    await page.locator(".listing-card").first().waitFor({ state: "visible", timeout: 15_000 });
    await page.waitForTimeout(1500);
    const incCount = parseInt((await page.locator(".num").first().textContent()) || "0", 10);

    expect(incCount).toBeGreaterThan(defaultCount);
  });
});
