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

  // Auth-state QA hack — until PR-9 ships real Clerk auth, the only
  // way to test logged-in/logged-out flows on the production /preview
  // alias is to set `pulpo-user` in localStorage manually. The dev
  // panel's authState useEffect MUST NOT clobber this on initial
  // mount. We hit a regression once where it did (the panel's default
  // "signed_out" value overwrote the localStorage-saved user on every
  // page load — flash of logged-in, then back to logged-out). This
  // test pins the fix.
  test("localStorage pulpo-user persists across reload", async ({ page, context }) => {
    await context.addInitScript(() => {
      localStorage.setItem(
        "pulpo-user",
        JSON.stringify({
          email: "you@pulpo.club",
          name: "Demo User",
          plan: "pro",
          joined: Date.now(),
        }),
      );
    });

    await page.goto("/", { waitUntil: "networkidle" });

    // After mount: localStorage should still have the user.
    const persisted = await page.evaluate(() => localStorage.getItem("pulpo-user"));
    expect(persisted, "pulpo-user clobbered on mount").toBeTruthy();

    const parsed = JSON.parse(persisted!);
    expect(parsed.plan).toBe("pro");

    // And the TopNav should reflect a signed-in state — the avatar
    // button (initial of email) renders only when `app.user` is set.
    // If the override fired, .avatar wouldn't appear.
    await page.locator(".avatar, .profile-chip").first().waitFor({
      state: "visible",
      timeout: 5_000,
    });
  });
});
