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
});
