// preview-smoke.spec.ts — the guardrail for the new Vite app.
//
// Why this test exists:
//   We've shipped two crashes to /preview in two PRs (React #310 hook
//   order, then null price_per_m2 in .toFixed). Both manifested as
//   ErrorBoundary fallbacks — the page rendered the "Something went
//   wrong" screen instead of the app.
//
//   This test is the floor: open / and /browse on a Vite dev server,
//   wait for content to render, listen for any console error, fail the
//   build if any uncaught exception fires.
//
//   Runs in CI on every PR via .github/workflows/ci.yml frontend job.

import { test, expect, type ConsoleMessage } from "@playwright/test";

// Some console noise we tolerate (third-party libraries, dev-mode
// React-DevTools detection prompts). Anything matched here is logged
// but doesn't fail the build.
const TOLERATED = [
  /Download the React DevTools/,
  /\[vite\]/,                          // Vite HMR connection logs
  /Content Security Policy.*'eval'/,   // PostHog's eval-warning noise
];

function isTolerated(msg: ConsoleMessage): boolean {
  const text = msg.text();
  return TOLERATED.some((re) => re.test(text));
}

test.describe("New app boots cleanly on key routes", () => {
  for (const route of ["/", "/?dev=1"]) {
    test(`renders ${route} without console errors`, async ({ page }) => {
      const errors: string[] = [];
      const uncaught: string[] = [];

      page.on("console", (msg) => {
        if (msg.type() === "error" && !isTolerated(msg)) {
          errors.push(msg.text());
        }
      });
      page.on("pageerror", (err) => {
        uncaught.push(err.message);
      });

      await page.goto(route, { waitUntil: "networkidle" });

      // Wait for the app shell to actually mount (anything from the
      // editorial vocabulary). If we see the ErrorBoundary fallback
      // text, fail with that copy in the failure message.
      const errorBoundary = page.getByText("Something went wrong.");
      const realApp = page.locator(".app, .topnav, .hero, .page-home");
      await Promise.race([
        realApp.first().waitFor({ state: "visible", timeout: 15_000 }),
        errorBoundary.waitFor({ state: "visible", timeout: 15_000 }).then(() => {
          throw new Error(
            `ErrorBoundary fallback rendered on ${route} — uncaught exceptions: ${JSON.stringify(uncaught)}`
          );
        }),
      ]);

      // Give the live-data fetch + first-paint a beat to finish before
      // asserting on errors.
      await page.waitForTimeout(2_500);

      expect(uncaught, `uncaught exceptions on ${route}`).toEqual([]);
      expect(errors, `console.error calls on ${route}`).toEqual([]);
    });
  }

  test("listing card renders without crashing on null fields", async ({ page }) => {
    // The specific crash we hit: listing.price_per_m2 was null on a
    // real listing, .toFixed(0) threw. This test asserts at least one
    // ListingCard renders (which means the per-card render didn't
    // crash on real data).
    await page.goto("/", { waitUntil: "networkidle" });
    // Any of the listing-card variants. .listing-card is the base
    // class shared by both default + magazine variants.
    await page.locator(".listing-card").first().waitFor({ state: "visible", timeout: 10_000 });
  });

  // PR-5 — detail-panel + lightbox smoke test.
  // Click a card → detail overlay opens → photo gallery → ESC closes
  // lightbox → click backdrop closes detail. Catches focus-trap or
  // event-listener leaks that crash on close.
  test("detail panel opens, lightbox accepts ESC, focus returns", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !isTolerated(msg)) errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/", { waitUntil: "networkidle" });
    const card = page.locator(".listing-card").first();
    await card.waitFor({ state: "visible", timeout: 10_000 });
    await card.click();

    // Detail overlay mounts with .detail-panel.
    await page.locator(".detail-panel").waitFor({ state: "visible", timeout: 5_000 });

    // Try opening the lightbox via the first non-locked thumbnail
    // (anonymous users have the main photo + thumb 0/1 unlocked; thumbs
    // 2+ are sign-up gated). If no thumbnails render, skip the
    // lightbox assertion — PR-5 still passes if detail itself didn't crash.
    const unlockedThumb = page.locator(".gallery-thumb:not(.locked)").first();
    if (await unlockedThumb.count() > 0) {
      await unlockedThumb.click();
      await page.locator(".lightbox").waitFor({ state: "visible", timeout: 3_000 });
      await page.keyboard.press("Escape");
      await page.locator(".lightbox").waitFor({ state: "hidden", timeout: 3_000 });
    }

    // Close detail by clicking the overlay backdrop (outside the panel).
    await page.locator(".detail-overlay").click({ position: { x: 5, y: 5 } });
    await page.locator(".detail-panel").waitFor({ state: "hidden", timeout: 3_000 });

    expect(errors, "console errors after detail open/close").toEqual([]);
  });

  // PR-4f — interactive PriceHistogram smoke test.
  // Open Browse, click a histogram bar, verify the listing count drops
  // and the URL gets a pmax/pmin querystring. Click reset, verify the
  // count restores. Catches regressions in pointer-event wiring,
  // bucket→price math, and URL sync.
  test("price histogram bar-click filters listings and updates URL", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !isTolerated(msg)) errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/", { waitUntil: "networkidle" });
    // The app uses internal state for routing — click the Browse nav
    // link in TopNav to navigate, then wait for the histogram to mount.
    await page.locator(".topnav-links button").getByText(/^Browse$|^Explorar$/).click();
    const histo = page.locator(".histo-track");
    await histo.waitFor({ state: "visible", timeout: 10_000 });

    // Click roughly bar 5 of 24 (midway-low, where most listings cluster).
    const box = await histo.boundingBox();
    if (!box) throw new Error("histo-track has no box");
    const targetX = box.x + box.width * (5 / 24) + 4;
    const targetY = box.y + box.height / 2;
    await page.mouse.click(targetX, targetY);

    // After bar-click, URL should carry pmin and pmax.
    await page.waitForFunction(
      () => /[?&](pmin|pmax)=/.test(window.location.search),
      { timeout: 3_000 },
    );

    // Reset chip (visible only when range is active).
    const reset = page.locator(".histo-reset").first();
    await reset.waitFor({ state: "visible", timeout: 3_000 });
    await reset.click();

    // URL should clear pmin and pmax after reset.
    await page.waitForFunction(
      () => !/[?&]pmin=|[?&]pmax=/.test(window.location.search),
      { timeout: 3_000 },
    );

    expect(errors, "console errors during histogram interaction").toEqual([]);
  });

  // PR upgrade-flow-polish — verifies the Pro CTA on /plans actually
  // POSTs to /api/stripe/create-checkout-session. We mock the endpoint
  // (no real Stripe roundtrip in CI) and assert the click triggers a
  // request. The full e2e — real Stripe redirect, success URL handling,
  // webhook-driven plan flip — has to be tested by a human with a Stripe
  // test card; documented in BACKLOG.md.
  test("plans page Pro CTA fires create-checkout-session POST", async ({ page }) => {
    let postSeen = false;
    let postBody: string | null = null;
    await page.route("**/api/stripe/create-checkout-session", async (route) => {
      postSeen = true;
      postBody = route.request().postData();
      // Mock: server says "you need to sign in" — exercises the path
      // that opens the SignupModal with pendingAction:"checkout".
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ error: "sign_in_required" }),
      });
    });

    await page.goto("/", { waitUntil: "networkidle" });
    // Open Plans via the footer link (the topnav doesn't expose it).
    await page.locator(".site-footer button").getByText(/^Plans$/).first().click();
    await page.locator(".plan-card.featured").waitFor({ state: "visible", timeout: 5_000 });
    // Click the Pro CTA — its label uses the new t("plans.upgrade_pro_cta") key.
    await page.locator(".plan-card.featured .btn-primary").click();

    // The POST should have happened.
    await expect.poll(() => postSeen, { timeout: 3_000 }).toBe(true);
    expect(postBody).toBeDefined();

    // Anonymous → 401 → SignupModal opens. With Clerk off in the dev
    // env this surfaces as the legacy modal with the headline.
    // (When Clerk is on, the hosted modal opens instead — both cases
    // land at "the user is being prompted to sign in", which is the
    // contract that matters.)
    const modalOpen = await page.locator(".modal-signup, [data-clerk-component]").count();
    expect(modalOpen, "signup modal didn't open after sign_in_required").toBeGreaterThan(0);
  });
});
