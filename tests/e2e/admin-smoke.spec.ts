// admin-smoke.spec.ts — guardrail for the open /admin hub.
//
// The page is open by design (no auth). What this test enforces:
//   - /admin renders the widget grid without console errors
//   - /admin/newsletter renders the NewsletterWidget without errors
//   - /admin/this-widget-does-not-exist renders the "unknown widget"
//     fallback instead of crashing
//   - the meta robots tag is set to noindex on /admin
//
// The newsletter widget is a tiny trigger that dispatches the
// `pulpo-newsletter` GH Actions workflow with `preview_cohorts=<email>`.
// This spec covers rendering only; the dispatch behavior lives in the
// trigger-preview endpoint (admin-token-gated, so not exercised here).

import { test, expect } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

test.describe("/admin", () => {
  test("renders the widget grid", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto("/admin", { waitUntil: "networkidle" });

    // Title check — set by AdminShell's effect.
    await expect(page).toHaveTitle(/Pulpo admin/i);

    // Robots noindex must be present so the page isn't accidentally
    // indexed even if robots.txt is missed by a crawler.
    const robotsContent = await page
      .locator('meta[name="robots"]')
      .getAttribute("content");
    expect(robotsContent || "").toMatch(/noindex/);

    // The newsletter widget card is one of the registered entries.
    await expect(page.getByText("Newsletter preview")).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("opens the newsletter widget by URL", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto("/admin/newsletter", { waitUntil: "networkidle" });

    // Title now carries the widget label.
    await expect(page).toHaveTitle(/Newsletter preview/i);

    // The widget renders the "Send test to" preview-email input
    // (empty by default since DEFAULT_EMAIL = "" — the operator types
    // a recipient each iteration so a stale hardcoded address can
    // never silently fire). Per-newsletter cards live below; at least
    // one Pro newsletter card is in the live state on production.
    //
    // Earlier shape ("preview recipient" label + "send next 3 cohort
    // variants" button + prefilled javier@suarez.ventures) was
    // retired across PR-NL-9 → #560 → #566 → #578 → #583 → #634 as
    // the widget moved from a single-cohort trigger to the per-
    // newsletter registry with tier sections.
    await expect(page.getByLabel(/send test to/i)).toHaveValue("");
    await expect(page.getByPlaceholder("you@example.com")).toBeVisible();
    await expect(page.locator(".nl-tier-label.pro").first()).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("unknown widget slug falls back to the grid + empty-state notice", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto("/admin/this-widget-does-not-exist", { waitUntil: "networkidle" });

    // Even with an unknown slug we should not crash — the page renders
    // the widget grid and an inline "unknown widget" notice.
    await expect(page.getByText("Newsletter preview")).toBeVisible();
    await expect(page.getByText(/Unknown widget/i)).toBeVisible();

    expect(errors).toEqual([]);
  });
});
