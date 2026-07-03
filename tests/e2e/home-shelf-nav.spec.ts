// Home shelves are navigation, not gated detail. A shelf card click takes a
// Free/anonymous visitor to the filtered Discover view — NOT the access
// modal and NOT a detail panel. The panel access gate lives on Discover
// (openListing), so browsing the catalogue is free; only opening a listing
// hits the gate.

import { test, expect } from "@playwright/test";
import { seedConsent } from "./_helpers";

test("anonymous: home shelf card → Discover (filtered), no gate modal/panel", async ({ page }) => {
  await seedConsent(page);
  await page.goto("/", { waitUntil: "networkidle" });

  const card = page.locator(".hp-shelf-card-real").first();
  await expect(card).toBeVisible({ timeout: 8_000 });
  await card.scrollIntoViewIfNeeded();
  await card.click();

  // Landed on Discover, filtered to the shelf's category…
  await expect(page).toHaveURL(/\/browse\?.*\bcat=/, { timeout: 8_000 });
  // …with NO access gate and NO detail panel (browsing is free).
  await expect(page.locator(".access-modal")).toHaveCount(0);
  await expect(page.locator(".detail-panel")).toHaveCount(0);
});
