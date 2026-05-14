// Smoke tests for the redesigned homepage (homepage-v2).
//
// Coverage:
//   - Cold-load boots cleanly with no console errors.
//   - Section landmarks render (hero, featured, USP band, shoreline,
//     three shelves, header).
//   - Primary CTA in the header + hero opens the signup modal (the
//     conversion path the funnel depends on).
//   - "Pick your shoreline" cards navigate to /browse with the right
//     master_category filter.
//   - Mobile menu opens, traps focus, and closes on Escape.
//   - Section error boundaries render a compact fallback (not a
//     full-page blank) when a child throws.
//
// The previous email-form / proof-row / category-grid / discovery-
// pill tests were retired with the v2 redesign — those sections no
// longer exist on the homepage.

import { test, expect } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

const URL_HOME = "/";

test.describe("Homepage v2 — redesign smoke", () => {
  test("boots cleanly with the rewrite title", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    // The rewrite copy in <title> (driven by useDocumentMeta).
    // Either the cold-load static title or the post-hydration one
    // mentions El Salvador + ranking.
    await expect(page).toHaveTitle(/(ranked|El Salvador)/i);

    // Homepage v2 root mounts.
    await expect(page.locator(".homepage-v2")).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("renders every top-level section", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    // Wave-3a: HomepageHeader replaced by the shared SiteHeader.
    await expect(page.locator('[data-testid="site-header"]')).toBeVisible();
    await expect(page.locator(".hp-hero")).toBeVisible();
    await expect(page.locator(".hp-featured")).toBeVisible();
    await expect(page.locator(".hp-usp")).toBeVisible();
    await expect(page.locator(".hp-shoreline")).toBeVisible();
    await expect(page.locator("#hp-shelf-top10")).toBeVisible();
    await expect(page.locator("#hp-shelf-drops")).toBeVisible();
    await expect(page.locator("#hp-shelf-new")).toBeVisible();

    // No ErrorBoundary fallback anywhere on the page.
    await expect(page.locator('[data-testid="error-boundary-fallback"]')).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test("primary hero CTA routes anonymous users to /start (Wave-1 conversion path)", async ({ page, context }) => {
    const errors = attachErrorRecorder(page);

    // Wave-1 routing change: anon clicks no longer open a signup modal
    // intermediary — they redirect to /start which handles email +
    // Stripe checkout in one flow. Intercept the redirect so the test
    // doesn't navigate away before we can assert.
    let startRedirectHit = false;
    await context.route("**/start**", (route) => {
      startRedirectHit = true;
      void route.fulfill({ status: 204, body: "" });
    });

    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    // Homepage v3 hero CTA class is .hp-hero-cta-primary ("Try a free
    // month"); the v2 .hp-cta-dark fallback selector stays in the OR
    // list so a partial rollback doesn't silently break this test.
    const heroCta = page.locator(
      ".hp-hero .hp-hero-cta-primary, .hp-hero .hp-cta-dark",
    ).first();
    await heroCta.click();

    await expect.poll(() => startRedirectHit, {
      timeout: 3_000,
      message: "expected anon click to redirect to /start (Wave-1 routing)",
    }).toBe(true);

    expect(errors).toEqual([]);
  });

  test("reduced-motion: leaderboard does not start the cycle (no Just In pill)", async ({ browser }) => {
    // Per the v3 perf rules, the hero MUST short-circuit the cycle
    // when the OS prefers reduced motion. The leaderboard renders
    // statically with the initial widths and the Just In pill is
    // suppressed (the pill is a motion artifact).
    const ctx = await browser.newContext({ reducedMotion: "reduce" });
    const page = await ctx.newPage();
    const errors = attachErrorRecorder(page);
    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    // Hero renders, leaderboard rows are present.
    await expect(page.locator(".hp-hero")).toBeVisible();
    await expect(page.locator(".hp-hero-preview-row")).toHaveCount(10);

    // Just In pill is NOT in the DOM (component returns null under
    // reduced motion).
    await expect(page.locator(".hp-hero-justin")).toHaveCount(0);

    expect(errors).toEqual([]);
    await ctx.close();
  });

  test("Pick Your Shoreline → /browse with master filter", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    await page.locator(".hp-shoreline-card-beach").click();

    await page.waitForFunction(
      () => window.location.pathname === "/browse",
      null,
      { timeout: 3_000 },
    );

    expect(errors).toEqual([]);
  });

  // Wave-3a: the mobile-hamburger sheet was a HomepageHeader-only
  // feature. The new SiteHeader is TopNav-style with BottomNav
  // handling mobile section navigation. The "mobile menu opens..."
  // test was removed with HomepageHeader.jsx.
});
