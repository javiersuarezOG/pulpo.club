// Regression guard for the FreeMemberAccount desktop layout.
//
// Bug (shipped in PR #846, found 2026-07-04): the free-member /account
// container carried BOTH classes — `account-layout account-layout-free`.
// `.account-layout` (grid: 220px 1fr) is defined ~290 lines AFTER
// `.account-layout-free` (display: block) in index.css. Equal specificity
// → later source order wins → the free view rendered as a two-column grid.
// The single <main> landed in the 220px nav column; the 1fr column stayed
// empty. Desktop-only: at ≤767px the grid collapses to 1fr, so mobile
// looked fine and the mobile-first responsive-smoke never caught it.
//
// The existing responsive-smoke seeds `plan:"free"` WITHOUT
// `email_member:true`, so it renders the tabbed account, never
// <FreeMemberAccount>. This spec seeds a real free member and asserts the
// content is a centered single column, not squished into the 220px grid
// column.

import { expect, test } from "@playwright/test";
import { attachErrorRecorder, seedConsent, seedFreeMember } from "./_helpers";

test.describe("free-member /account layout", () => {
  test("renders as a centered single column at desktop width, not the grid", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const errors = attachErrorRecorder(page);
    await seedFreeMember(page);
    await seedConsent(page);

    await page.goto("/account", { waitUntil: "networkidle" });

    const layout = page.locator(".account-layout-free");
    await expect(layout).toBeVisible();

    // The bug rendered this as a grid (inherited from .account-layout).
    const display = await layout.evaluate((el) => getComputedStyle(el).display);
    expect(display, "free layout must not be the two-column grid").not.toBe("grid");

    // When broken, <main class="account-free"> is trapped in the 220px
    // grid column. Fixed, it spans up to the 560px centered block. 400px
    // cleanly separates the two states.
    const box = await page.locator(".account-free").boundingBox();
    expect(box, "account-free main must render").not.toBeNull();
    expect(box!.width, "free content must not be squished into the 220px nav column").toBeGreaterThan(400);

    expect(errors, "console errors on free-member /account").toEqual([]);
  });
});
