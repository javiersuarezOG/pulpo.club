// /account/notifications — preferred-category chip selector (PR-B).
//
// Covers:
//   - Pro user sees chips under the newsletter toggle
//   - Pick 4 chips → all active; 5th is no-op + limit hint shown
//   - Reload → selection persists (localStorage path; PR-C wires Clerk)
//   - Newsletter toggle off → chip group disappears
//   - ES locale: chips render their Spanish copy; English canaries
//     ("Price drops", "Beachfront") DON'T appear

import { test, expect } from "@playwright/test";
import { attachErrorRecorder, seedProUser } from "./_helpers";

test.describe("/account/notifications — preferred categories", () => {
  test("Pro user can pick up to 4 chips; 5th no-ops + limit hint", async ({ page }) => {
    await seedProUser(page);
    const errors = attachErrorRecorder(page);
    await page.goto("/account/notifications", { waitUntil: "networkidle" });

    const grid = page.locator('[data-chip-group="preferred-categories"]');
    await grid.waitFor({ state: "visible", timeout: 10_000 });

    // Exactly six chips render (matches PREFERENCE_CATEGORY_KEYS length).
    await expect(grid.locator("[data-category-key]")).toHaveCount(6);

    const keys = ["new_this_week", "price_drops", "beachfront", "water_features"];
    for (const k of keys) {
      await grid.locator(`[data-category-key="${k}"]`).click();
    }
    for (const k of keys) {
      await expect(
        grid.locator(`[data-category-key="${k}"]`),
        `chip ${k} active after click`,
      ).toHaveAttribute("aria-checked", "true");
    }

    // 5th click — must be no-op.
    const fifth = grid.locator('[data-category-key="under_50k"]');
    await fifth.click();
    await expect(fifth, "5th chip stays inactive").toHaveAttribute("aria-checked", "false");
    await expect(
      page.locator(".notif-categories-limit"),
      "limit hint visible",
    ).toBeVisible();

    // Deselect one → free up a slot → previously-blocked chip can now activate.
    await grid.locator('[data-category-key="water_features"]').click();
    await expect(
      grid.locator('[data-category-key="water_features"]'),
      "water_features now inactive",
    ).toHaveAttribute("aria-checked", "false");
    await fifth.click();
    await expect(fifth, "under_50k now active").toHaveAttribute("aria-checked", "true");

    expect(errors, "console errors during chip flow").toEqual([]);
  });

  test("selection persists across reload (localStorage path)", async ({ page }) => {
    // Non-clobbering seed: addInitScript runs on every navigation
    // INCLUDING reload, so a plain `seedProUser` here would overwrite
    // the profile we wrote between the click and the reload. Guard the
    // seed with an existence check so subsequent reloads preserve the
    // app's writes.
    await page.addInitScript(() => {
      if (!localStorage.getItem("pulpo-user")) {
        localStorage.setItem("pulpo-user", JSON.stringify({
          email: "pro-tester@pulpo.club",
          name: "Pro Tester",
          plan: "pro",
          joined: Date.now(),
          provider: "email",
        }));
      }
    });
    await page.goto("/account/notifications", { waitUntil: "networkidle" });
    await page.locator('[data-chip-group="preferred-categories"]').waitFor({ state: "visible", timeout: 10_000 });

    await page.locator('[data-category-key="beachfront"]').click();
    await page.locator('[data-category-key="under_100k"]').click();

    await page.reload({ waitUntil: "networkidle" });
    await page.locator('[data-chip-group="preferred-categories"]').waitFor({ state: "visible", timeout: 10_000 });

    await expect(page.locator('[data-category-key="beachfront"]')).toHaveAttribute("aria-checked", "true");
    await expect(page.locator('[data-category-key="under_100k"]')).toHaveAttribute("aria-checked", "true");
    // Untouched chips stay inactive.
    await expect(page.locator('[data-category-key="new_this_week"]')).toHaveAttribute("aria-checked", "false");
  });

  test("toggling newsletter off hides the chip group entirely", async ({ page }) => {
    await seedProUser(page);
    await page.goto("/account/notifications", { waitUntil: "networkidle" });
    await page.locator('[data-chip-group="preferred-categories"]').waitFor({ state: "visible", timeout: 10_000 });

    // The newsletter toggle is a role="switch" with aria-label set to
    // the newsletter title — flip it.
    const newsletterToggle = page
      .locator('button[role="switch"][aria-label*="newsletter"i], button[role="switch"][aria-label*="boletín"i]')
      .first();
    await newsletterToggle.click();

    await expect(page.locator('[data-chip-group="preferred-categories"]')).toHaveCount(0);
  });

  test("ES locale: chips render Spanish copy; English canaries absent", async ({ page }) => {
    await seedProUser(page);
    await page.addInitScript(() => {
      try { localStorage.setItem("pulpo-locale", "es"); } catch {}
    });
    await page.goto("/account/notifications", { waitUntil: "networkidle" });
    await page.locator('[data-chip-group="preferred-categories"]').waitFor({ state: "visible", timeout: 10_000 });

    const gridText = (await page.locator('[data-chip-group="preferred-categories"]').innerText()).toLowerCase();
    // Spanish copy present. Note: i18n source uses "Nuevas esta semana"
    // (feminine, matches "nuevas casas/propiedades") and "Rebajas de
    // precio" — keep these assertions aligned with web/app/i18n.jsx.
    expect(gridText).toContain("nuevas");
    expect(gridText).toContain("rebajas de precio");
    expect(gridText).toContain("frente al mar");
    // English canaries absent — each represents an i18n bug we'd
    // otherwise ship silently. Adding a new chip whose EN label would
    // look fine in ES? Add it here, not to a SHARED_TOKENS allowlist.
    for (const canary of [
      "Price drops",
      "Beachfront",
      "Lakefront",
      "New this week",
    ]) {
      expect(
        gridText,
        `Spanish locale leaked English chip label: "${canary}"`,
      ).not.toContain(canary.toLowerCase());
    }
  });
});
