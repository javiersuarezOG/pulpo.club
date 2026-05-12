// Home-page Pro upsell modal — trigger logic E2E (PR-C).
//
// The trigger truth-table from web/app/lib/upsell-config.ts:
//   - / (no params)                → no modal (showForDirectTraffic=false)
//   - /?utm_source=reddit          → modal
//   - /?code=REDDIT01              → modal
//   - /?upsell=1                   → modal (force-on)
//   - /?utm_source=…&upsell=0      → no modal (force-off wins)
//   - Pro user + anything          → no modal
//   - Dismissed within 7 days      → no modal
//
// Each row here is one Playwright test. The decision logic is pure
// (lib/upsell-config.ts) so we test the *integration* — that HomePage
// actually wires it up — not the function in isolation.

import { test, expect } from "@playwright/test";
import { attachErrorRecorder, seedProUser } from "./_helpers";

const MODAL = ".pro-upsell-modal";

// Playwright contexts are fresh per test by default (browser.newContext()
// for each), so localStorage is clean — no shared suppression state to
// reset. The `Dismiss → reload within suppression window → no modal`
// test below RELIES on the suppression key being set by markUpsellDismissed
// and surviving across the reload, so a global addInitScript that wipes
// the key would defeat that assertion.

test.describe("Home page Pro upsell modal — trigger logic", () => {
  test("Direct traffic (/ no params) → no modal", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto("/", { waitUntil: "networkidle" });
    await page.locator(".homepage-v2, .new-homepage, .new-hero").first().waitFor({ state: "visible", timeout: 10_000 });
    // Give the post-mount HomePage effect a tick to fire (it would
    // open the modal if the decision said yes).
    await page.waitForTimeout(800);

    await expect(page.locator(MODAL)).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("/?utm_source=reddit → modal renders", async ({ page }) => {
    await page.goto("/?utm_source=reddit", { waitUntil: "networkidle" });
    await page.locator(MODAL).waitFor({ state: "visible", timeout: 5_000 });
    // Three USPs visible inside the modal.
    await expect(page.locator(".pro-upsell-usps li")).toHaveCount(3);
    // Primary CTA + dismiss button both present.
    await expect(page.locator(".pro-upsell-cta-primary")).toBeVisible();
    await expect(page.locator(".pro-upsell-cta-dismiss")).toBeVisible();
  });

  test("/?code=REDDIT01 → modal + discount note", async ({ page }) => {
    await page.goto("/?code=REDDIT01", { waitUntil: "networkidle" });
    await page.locator(MODAL).waitFor({ state: "visible", timeout: 5_000 });
    await expect(page.locator(".pro-upsell-code-note")).toBeVisible();
  });

  test("/?upsell=1 → modal (explicit force-on)", async ({ page }) => {
    await page.goto("/?upsell=1", { waitUntil: "networkidle" });
    await page.locator(MODAL).waitFor({ state: "visible", timeout: 5_000 });
  });

  test("/?utm_source=reddit&upsell=0 → no modal (force-off wins)", async ({ page }) => {
    await page.goto("/?utm_source=reddit&upsell=0", { waitUntil: "networkidle" });
    await page.locator(".homepage-v2, .new-homepage, .new-hero").first().waitFor({ state: "visible", timeout: 10_000 });
    await page.waitForTimeout(800);
    await expect(page.locator(MODAL)).toHaveCount(0);
  });

  test("Pro signed-in user → no modal even with utm", async ({ page }) => {
    await seedProUser(page);
    await page.goto("/?utm_source=reddit", { waitUntil: "networkidle" });
    await page.locator(".homepage-v2, .new-homepage, .new-hero").first().waitFor({ state: "visible", timeout: 10_000 });
    await page.waitForTimeout(800);
    await expect(page.locator(MODAL)).toHaveCount(0);
  });

  test("Dismiss → reload within suppression window → no modal", async ({ page }) => {
    await page.goto("/?utm_source=reddit", { waitUntil: "networkidle" });
    await page.locator(MODAL).waitFor({ state: "visible", timeout: 5_000 });

    // Dismiss via the "Maybe later" link — exercises the dismissal path
    // that also stamps localStorage (markUpsellDismissed).
    await page.locator(".pro-upsell-cta-dismiss").click();
    await page.locator(MODAL).waitFor({ state: "detached", timeout: 5_000 });

    // Reload with the same utm — the 7-day suppression should suppress
    // re-show.
    await page.reload({ waitUntil: "networkidle" });
    await page.locator(".homepage-v2, .new-homepage, .new-hero").first().waitFor({ state: "visible", timeout: 10_000 });
    await page.waitForTimeout(800);
    await expect(page.locator(MODAL)).toHaveCount(0);
  });
});

test.describe("Home upsell modal — CTA wiring", () => {
  test("Click 'Get access' → POST /api/stripe/start-checkout → redirect", async ({ page }) => {
    await page.route("**/api/stripe/start-checkout", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ url: "http://localhost:5173/?stripe-redirect=ok", sessionId: "cs_test_mock" }),
      });
    });

    let postBody: Record<string, unknown> | null = null;
    page.on("request", (req) => {
      if (req.url().includes("/api/stripe/start-checkout") && req.method() === "POST") {
        const raw = req.postData();
        if (raw) {
          try { postBody = JSON.parse(raw); } catch { /* ignore */ }
        }
      }
    });

    await page.goto("/?code=REDDIT01&utm_source=reddit", { waitUntil: "networkidle" });
    await page.locator(MODAL).waitFor({ state: "visible", timeout: 5_000 });
    await page.locator(".pro-upsell-cta-primary").click();
    await page.waitForURL(/stripe-redirect=ok/, { timeout: 5_000 });

    // Verify the modal's CTA POSTed the same payload /start would —
    // single backend, single source of truth.
    expect(postBody).toMatchObject({
      promoCode: "REDDIT01",
      utm_source: "reddit",
      locale: "en",
    });
  });
});
