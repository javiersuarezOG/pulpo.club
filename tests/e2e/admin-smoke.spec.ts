// admin-smoke.spec.ts — guardrail for the open /admin hub.
//
// The page is open by design (no auth). What this test enforces:
//   - /admin renders the widget grid without console errors
//   - /admin/newsletter renders the NewsletterWidget without errors
//   - /admin/this-widget-does-not-exist renders the "unknown widget"
//     fallback instead of crashing
//   - the meta robots tag is set to noindex on /admin
//
// Send / preview API behavior is exercised by the unit tests under
// tests/api (added alongside the endpoints). This spec is pure UI.

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

    // The newsletter widget card is the first (and currently only) entry.
    await expect(page.getByText("Newsletter preview & send")).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("opens the newsletter widget by URL", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto("/admin/newsletter", { waitUntil: "networkidle" });

    // Title now carries the widget label.
    await expect(page).toHaveTitle(/Newsletter preview & send/i);

    // The widget renders its form — the recipients field is prefilled
    // with the admin owner's email.
    await expect(page.getByText("Send to (max 5)")).toBeVisible();
    await expect(page.getByText("javier@suarez.ventures")).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("unknown widget slug falls back to the grid + empty-state notice", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto("/admin/this-widget-does-not-exist", { waitUntil: "networkidle" });

    // Even with an unknown slug we should not crash — the page renders
    // the widget grid and an inline "unknown widget" notice.
    await expect(page.getByText("Newsletter preview & send")).toBeVisible();
    await expect(page.getByText(/Unknown widget/i)).toBeVisible();

    expect(errors).toEqual([]);
  });
});
