// Regression guard for the free-join celebration overlay (JoinCelebration).
//
// Bug (reported 2026-07-04): after a free signup the "you're in / see my
// picks" reveal auto-dismissed on a 4.2s timer (2.6s under reduced motion),
// yanking the payoff away before the user could read it or tap the CTA.
//
// Contract now: the overlay PERSISTS until an explicit user action — the CTA,
// the close (×) button, or Escape. Backdrop taps must NOT close it (a stray
// tap is common on mobile). Verified at mobile + desktop widths.

import { expect, test, type Page } from "@playwright/test";
import { seedConsent } from "./_helpers";

const VIEWPORTS = [
  { name: "mobile 375", width: 375, height: 812 },
  { name: "desktop 1280", width: 1280, height: 800 },
];

// Drive the real production path: hero email form → POST /api/newsletter →
// becomeFreeMember → app-level celebration. The Vite dev server doesn't serve
// the serverless /api/newsletter, so we stub a success response.
//
// The hero renders one of two email forms depending on the `accessV2` flag
// (AccessBlock `.access-input` when on — the local default; EmailCapture
// `.hv6-signup-input` when off — the CI default). Both POST /api/newsletter
// and both call becomeFreeMember, so we target whichever is present.
async function openCelebration(page: Page): Promise<void> {
  await page.route("**/api/newsletter", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await seedConsent(page);
  await page.goto("/", { waitUntil: "networkidle" });
  const input = page.locator(".access-input, .hv6-signup-input").first();
  await input.fill("celebration-tester@pulpo.club");
  await page.locator(".access-cta-free, .hv6-signup-btn").first().click();
  await expect(page.locator(".jc-panel")).toBeVisible();
}

for (const vp of VIEWPORTS) {
  test.describe(`join celebration · ${vp.name}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
    });

    test("persists past the old auto-dismiss window, then closes via the CTA", async ({ page }) => {
      await openCelebration(page);

      // The old timer fired at 4200ms. Wait comfortably past it and assert the
      // overlay is still there — this is the exact regression.
      await page.waitForTimeout(4800);
      await expect(page.locator(".jc-panel"), "overlay must NOT auto-dismiss").toBeVisible();

      await page.locator(".jc-cta").click();
      await expect(page.locator(".jc-panel"), "CTA must close the overlay").toBeHidden();
    });

    test("ignores backdrop taps and closes via the × button", async ({ page }) => {
      await openCelebration(page);

      // Tap the backdrop's top-left corner (outside the panel). Must NOT close.
      await page.locator(".jc-backdrop").click({ position: { x: 5, y: 5 } });
      await expect(page.locator(".jc-panel"), "backdrop tap must NOT close the overlay").toBeVisible();

      await page.locator(".jc-close").click();
      await expect(page.locator(".jc-panel"), "× button must close the overlay").toBeHidden();
    });
  });
}

// Returning member (server → already_subscribed) gets the SubscribeConfirm card
// (treatment B), NOT the octopus celebration. Same behaviour on every route;
// the hero is the representative surface.
test.describe("already-subscribed confirmation · mobile 375", () => {
  test("shows the confirmation card and NOT the celebration", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.route("**/api/newsletter", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, already_subscribed: true }) }),
    );
    await seedConsent(page);
    await page.goto("/", { waitUntil: "networkidle" });
    await page.locator(".access-input, .hv6-signup-input").first().fill("returning-tester@pulpo.club");
    await page.locator(".access-cta-free, .hv6-signup-btn").first().click();

    await expect(page.locator(".subscribe-confirm"), "confirmation card must show").toBeVisible();
    await expect(page.locator(".subscribe-confirm-title")).toContainText("already on the list");
    await expect(page.locator(".jc-panel"), "octopus celebration must NOT play for a returning member").toHaveCount(0);
  });
});
