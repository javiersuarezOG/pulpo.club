// Free top-3 view exemption — integration guard.
//
// The two-state model walls non-paid viewers out of listing detail, with
// ONE exception: this week's top 3 ranked picks open in FULL (incl. the
// broker/source outbound link) for anyone — same set the home hero shows.
// Ranks 4+ stay behind the Pro modal. See web/app/lib/free-view +
// app.jsx openListing + the deep-link backstop.
//
// The top-3 set is adapter-computed (card_eligible / thumbnail_url are
// derived), so it can't be recomputed from raw ranked.json here. The app
// exposes the live ids on `window.__pulpoTestIds` (DEV-only seam) and we
// drive deterministic deep-links off that.

import { test, expect, type Page } from "@playwright/test";
import { pathForListing } from "../../web/app/lib/url-routing";
import { seedConsent } from "./_helpers";

async function readTestIds(page: Page): Promise<{ freeViewable: string[]; walled: string | null }> {
  return await page.evaluate(async () => {
    for (let i = 0; i < 100; i++) {
      const ids = (window as unknown as { __pulpoTestIds?: { freeViewable: string[]; walled: string | null } }).__pulpoTestIds;
      if (ids && Array.isArray(ids.freeViewable) && ids.freeViewable.length >= 1 && ids.walled) return ids;
      await new Promise((r) => setTimeout(r, 100));
    }
    return (window as unknown as { __pulpoTestIds?: { freeViewable: string[]; walled: string | null } }).__pulpoTestIds
      || { freeViewable: [], walled: null };
  });
}

test.describe("Free top-3 view exemption (anonymous viewer)", () => {
  test("a top-3 pick opens the full detail panel (no paywall)", async ({ page }) => {
    await seedConsent(page);
    await page.goto("/", { waitUntil: "networkidle" });

    const ids = await readTestIds(page);
    expect(ids.freeViewable.length, "app should expose ≥1 free-viewable id").toBeGreaterThanOrEqual(1);

    // Deep-link straight to a top-3 listing — the deep-link backstop must
    // let an anonymous viewer through to the full panel.
    await page.goto(pathForListing(ids.freeViewable[0]), { waitUntil: "networkidle" });

    await expect(page.locator(".detail-panel")).toBeVisible({ timeout: 8_000 });
    await expect(page.locator(".free-month-modal"), "top-3 must not be walled").toHaveCount(0);
  });

  test("an anonymous non-top-3 deep link → start-free email capture (not Stripe)", async ({ page }) => {
    await seedConsent(page);
    await page.goto("/", { waitUntil: "networkidle" });

    const ids = await readTestIds(page);
    expect(ids.walled, "app should expose a walled (rank 4+) id").toBeTruthy();

    await page.goto(pathForListing(ids.walled as string), { waitUntil: "networkidle" });

    // Email-first: an anonymous visitor gets the start-free capture modal,
    // NOT the Pro/$9.99 modal and NOT the detail panel.
    await expect(page.locator(".email-capture-modal"), "anon should get start-free capture").toBeVisible({ timeout: 8_000 });
    await expect(page.locator(".free-month-modal")).toHaveCount(0);
    await expect(page.locator(".detail-panel")).toHaveCount(0);
  });

  test("submitting the capture modal makes a Free member who can open the top-3", async ({ page }) => {
    // The dev server doesn't run /api functions; mock the newsletter POST.
    await page.route("**/api/newsletter", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) }),
    );
    await seedConsent(page);
    await page.goto("/", { waitUntil: "networkidle" });
    const ids = await readTestIds(page);

    // Anonymous click on a top-3 → capture modal (email gate).
    await page.goto(pathForListing(ids.freeViewable[0]), { waitUntil: "networkidle" });
    // Top-3 deep links open for anyone (SEO), so drive the click gate from a
    // non-top-3 to force the capture modal, then become a member.
    await page.goto(pathForListing(ids.walled as string), { waitUntil: "networkidle" });
    await expect(page.locator(".email-capture-modal")).toBeVisible({ timeout: 8_000 });
    await page.locator(".email-capture-modal input[type=email]").fill("e2e-test@example.com");
    await page.locator(".email-capture-modal .hv6-signup-btn").click();
    await expect(page.locator(".email-capture-modal")).toHaveCount(0, { timeout: 8_000 });

    // Now a Free member: opening a top-3 by click works without a gate.
    await page.goto(pathForListing(ids.freeViewable[0]), { waitUntil: "networkidle" });
    await expect(page.locator(".detail-panel")).toBeVisible({ timeout: 8_000 });
    await expect(page.locator(".email-capture-modal")).toHaveCount(0);
  });
});
