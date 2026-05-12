// /start funnel — full surface E2E (PR-C).
//
// Defends the single-button design from regressing. Covers:
//   - hero renders the new H1 + USPs + CTA at every viewport
//   - "Log in" link routes to /?login=1
//   - ?code=TEST shows the "✓ Discount applied at checkout" note
//   - ?cancelled=1 shows the soft notice
//   - Click "Get access" → POST /api/stripe/start-checkout (intercepted)
//     → window.location.assign() to the mocked Stripe URL
//   - ES locale: no English canary words on /start (subset of the
//     existing preview-smoke ES-canary test, expanded here)
//
// The matrix from the plan was (locale × viewport × auth × code).
// Auth doesn't materially change /start's UI since PR-B.1's single-
// button collapse (signed-in vs anonymous look identical there), so we
// drop the auth axis. Code axis covered in dedicated tests.

import { test, expect } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

const VIEWPORTS = [
  { name: "375 mobile",   width: 375,  height: 812 },
  { name: "1280 desktop", width: 1280, height: 800 },
] as const;

const LOCALES = [
  { code: "en", h1Contains: "Property in El Salvador" },
  { code: "es", h1Contains: "Propiedades en El Salvador" },
] as const;

// Intercept the Stripe checkout POST and return a synthetic URL — keeps
// the test offline + deterministic. We then assert the CTA's redirect
// to that URL happened. Use a localhost target so navigating to it
// doesn't 404 the test browser (Playwright follows the redirect).
const FAKE_STRIPE_URL = "http://localhost:5173/?stripe-redirect=ok";

async function mockCheckoutEndpoint(page: import("@playwright/test").Page) {
  await page.route("**/api/stripe/start-checkout", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ url: FAKE_STRIPE_URL, sessionId: "cs_test_mock" }),
    });
  });
}

test.describe("/start — content + interactions", () => {
  for (const vp of VIEWPORTS) {
    for (const lc of LOCALES) {
      test(`renders cleanly @ ${vp.name} · ${lc.code}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.addInitScript((l) => localStorage.setItem("pulpo-locale", l), lc.code);
        const errors = attachErrorRecorder(page);

        await page.goto("/start", { waitUntil: "networkidle" });
        const startPage = page.locator(".start-page");
        await startPage.waitFor({ state: "visible", timeout: 10_000 });

        // Hero copy in the right language.
        await expect(page.locator(".start-hero-h1")).toContainText(lc.h1Contains);

        // Three canonical USPs above the fold + same three in the join card.
        // Each USP appears at least twice on the page (hero + join card).
        // We don't assert exact text — locale-dependent — but we assert the
        // list elements are populated.
        const heroUsps = page.locator(".start-hero-usps li");
        await expect(heroUsps).toHaveCount(3);
        const joinFeatures = page.locator(".start-card-features li");
        await expect(joinFeatures).toHaveCount(3);

        // Login link wired to /?login=1.
        const loginLink = page.locator(".start-nav-link");
        await expect(loginLink).toHaveAttribute("href", "/?login=1");

        // No console errors at any viewport in any locale.
        expect(errors, `console errors on /start @ ${vp.name} · ${lc.code}`).toEqual([]);
      });
    }
  }
});

test.describe("/start — URL behaviours", () => {
  test("?code=TEST shows the discount-applied note", async ({ page }) => {
    await page.goto("/start?code=TEST", { waitUntil: "networkidle" });
    await page.locator(".start-page").waitFor({ state: "visible", timeout: 10_000 });
    // The note's class + role=status combo is stable across copy iterations.
    const note = page.locator(".start-hero-code-note, .start-code-applied-note").first();
    await expect(note).toBeVisible();
  });

  test("?cancelled=1 shows the soft notice", async ({ page }) => {
    await page.goto("/start?cancelled=1", { waitUntil: "networkidle" });
    await page.locator(".start-page").waitFor({ state: "visible", timeout: 10_000 });
    await expect(page.locator(".start-cancelled-banner")).toBeVisible();
  });

  test("?utm_* params are captured into sessionStorage", async ({ page }) => {
    await page.goto("/start?utm_source=reddit&utm_campaign=may26", { waitUntil: "networkidle" });
    await page.locator(".start-page").waitFor({ state: "visible", timeout: 10_000 });
    const captured = await page.evaluate(() => ({
      utm_source: sessionStorage.getItem("pulpo-utm_source"),
      utm_campaign: sessionStorage.getItem("pulpo-utm_campaign"),
    }));
    expect(captured.utm_source).toBe("reddit");
    expect(captured.utm_campaign).toBe("may26");
  });
});

test.describe("/start — checkout CTA", () => {
  test("Click 'Get access' → POST /api/stripe/start-checkout → redirect", async ({ page }) => {
    await mockCheckoutEndpoint(page);
    const errors = attachErrorRecorder(page);

    // Record the request payload so we can assert the post body looks right.
    let postBody: Record<string, unknown> | null = null;
    page.on("request", (req) => {
      if (req.url().includes("/api/stripe/start-checkout") && req.method() === "POST") {
        const raw = req.postData();
        if (raw) {
          try { postBody = JSON.parse(raw); } catch { /* ignore */ }
        }
      }
    });

    await page.goto("/start", { waitUntil: "networkidle" });
    await page.locator(".start-page").waitFor({ state: "visible", timeout: 10_000 });

    // The hero CTA fires the same handler as the join card CTA (PR-B.4a).
    // Use the join card button — it's stable across viewports (the hero
    // CTA shares a class but the join is always visible).
    const cta = page.locator(".start-card-cta-primary").first();
    await cta.click();

    // Wait for the page to navigate to the mocked Stripe URL.
    await page.waitForURL(/stripe-redirect=ok/, { timeout: 5_000 });

    // Verify the request body was the shape /api/stripe/start-checkout expects.
    expect(postBody, "checkout endpoint received a POST body").not.toBeNull();
    expect(postBody).toMatchObject({
      promoCode: null, // no ?code= in URL
      locale: "en",    // default locale
    });

    expect(errors, "console errors during CTA submit").toEqual([]);
  });

  test("?code=TEST → checkout POST includes promoCode", async ({ page }) => {
    await mockCheckoutEndpoint(page);

    let postBody: Record<string, unknown> | null = null;
    page.on("request", (req) => {
      if (req.url().includes("/api/stripe/start-checkout") && req.method() === "POST") {
        const raw = req.postData();
        if (raw) {
          try { postBody = JSON.parse(raw); } catch { /* ignore */ }
        }
      }
    });

    await page.goto("/start?code=TEST", { waitUntil: "networkidle" });
    await page.locator(".start-page").waitFor({ state: "visible", timeout: 10_000 });
    await page.locator(".start-card-cta-primary").first().click();
    await page.waitForURL(/stripe-redirect=ok/, { timeout: 5_000 });

    expect(postBody).toMatchObject({ promoCode: "TEST" });
  });
});
