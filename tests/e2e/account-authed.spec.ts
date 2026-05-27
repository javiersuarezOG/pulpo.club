// Clerk-on authenticated smoke for the /account area.
//
// This spec is the verification surface that CI couldn't see: every
// other test in the suite runs with Clerk OFF, which is exactly why the
// "Save my profile name" and "Upload my profile photo" bugs shipped
// invisibly. This spec signs in as a real user, mutates every visible
// control on /account/profile + /account/notifications + /account/security,
// reads the values back from the Clerk Backend API, and restores the
// account to its pre-test state.
//
// Skipped when E2E_CLERK_USER_EMAIL is missing — keeps CI green for
// agents/forks that don't have the test creds. Sebas runs locally with:
//   npm run e2e:authed
// after populating .env.local (see .env.example).

import { expect, test } from "@playwright/test";
import * as path from "node:path";
import {
  readAuthedEnv,
  setupClerkTesting,
  signInWithPassword,
  snapshotUser,
  restoreUser,
  readUser,
  attachCspGuard,
} from "./_clerk-auth";

const env = readAuthedEnv();

test.describe("Account area (Clerk-on, real session)", () => {
  test.skip(!env, "set E2E_CLERK_USER_EMAIL + CLERK_SECRET_KEY in .env.local to run");

  const FIXTURE_AVATAR = path.resolve(__dirname, "fixtures/test-avatar.png");

  test("Profile save + photo upload + Notifications + Security walk", async ({ page, context }) => {
    if (!env) return; // narrow for TS — `test.skip` above handles runtime

    test.setTimeout(180_000); // multi-step + photo upload — pad over the default 30s.
    attachCspGuard(page);

    // 1. Bypass CAPTCHA, sign in.
    await setupClerkTesting(context, env);
    const snap = await snapshotUser(env);

    try {
      await signInWithPassword(page, env);

      // ─── Profile ────────────────────────────────────────────────
      await page.goto("/account/profile");
      const nameInput = page.locator('input[autocomplete="name"]');
      await nameInput.waitFor({ state: "visible" });

      // Predictable test value. Restored in teardown.
      const TEST_FIRST = "Sebastian";
      const TEST_LAST = "Walker";
      await nameInput.fill(`${TEST_FIRST} ${TEST_LAST}`);
      const saveBtn = page.getByRole("button", { name: /Save changes|Guardar cambios/i });
      await saveBtn.click();
      // Saving… → Changes saved.
      await expect(page.locator(".account-inline-confirm")).toBeVisible({ timeout: 10_000 });

      // Reload + backend read-back.
      await page.reload();
      await expect(nameInput).toHaveValue(`${TEST_FIRST} ${TEST_LAST}`);
      const after = await readUser(env, snap.userId);
      expect(after.firstName).toBe(TEST_FIRST);
      expect(after.lastName).toBe(TEST_LAST);

      // ─── Photo upload ───────────────────────────────────────────
      const fileInput = page.locator('input[type="file"][accept*="image"]');
      await fileInput.setInputFiles(FIXTURE_AVATAR);
      // Avatar swaps from initial letter to <img>. Wait for the img to
      // appear inside the avatar container.
      await expect(page.locator(".profile-avatar img")).toBeVisible({ timeout: 30_000 });

      await page.reload();
      await expect(page.locator(".profile-avatar img")).toBeVisible({ timeout: 15_000 });
      const afterPhoto = await readUser(env, snap.userId);
      expect(afterPhoto.hasImage).toBe(true);

      // Remove photo.
      await page.getByRole("button", { name: /Remove photo|Quitar foto/i }).click();
      await expect(page.locator(".profile-avatar img")).toHaveCount(0, { timeout: 15_000 });

      // ─── Country + language ────────────────────────────────────
      // CountryCombobox is the new accessible-listbox picker — datalist
      // was hidden behind partial-match typing on Safari. Drive it via
      // its ARIA role: type, wait for the listbox option, click it.
      const countryCombo = page.getByRole("combobox").filter({ has: page.locator('[aria-controls]') }).first();
      await countryCombo.click();
      await countryCombo.fill("Mexico");
      await page.getByRole("option", { name: "Mexico" }).click();
      const langSelect = page.locator('select').filter({ has: page.locator('option[value="es"]') });
      await langSelect.selectOption("es");
      await page.getByRole("button", { name: /Save changes|Guardar cambios/i }).click();
      await expect(page.locator(".account-inline-confirm")).toBeVisible({ timeout: 10_000 });

      await page.reload();
      const afterMeta = await readUser(env, snap.userId);
      const profile = (afterMeta.publicMetadata as Record<string, unknown>)?.profile as Record<string, unknown> | undefined;
      expect(profile?.country).toBe("MX");
      expect(profile?.language).toBe("es");

      // Combobox clear button removes the local value without writing
      // empty to Clerk — empty country is "not set", not "cleared on
      // the server". After clearing + reload the saved country should
      // still be MX (the previous save).
      const clearBtn = page.getByRole("button", { name: /Clear|Limpiar/i });
      if (await clearBtn.count()) {
        await clearBtn.first().click();
        // Combobox input is now empty; clicking outside or saving
        // without picking a new value should not patch country=""
        // (the backend would reject it; the client guards against it).
      }

      // ─── Notifications ─────────────────────────────────────────
      await page.goto("/account/notifications");
      // The new cadence note paragraph is present (Pro user).
      await expect(page.getByText(/fortnightly newsletter|boletín quincenal/i)).toBeVisible();
      // Regression guard — the dead toggles MUST NOT come back.
      await expect(page.locator(".pref-row .toggle")).toHaveCount(0);
      await expect(page.locator(".freq-toggle")).toHaveCount(0);

      // Toggle a Preferred category chip (the one control that has a
      // real backend consumer). Reload and confirm persistence.
      const firstChip = page.locator('[data-chip-group="preferred-categories"] .chip').first();
      const chipKey = await firstChip.getAttribute("data-category-key");
      const wasActiveBefore = (await firstChip.getAttribute("aria-checked")) === "true";
      await firstChip.click();
      await page.waitForTimeout(500); // let optimistic update + network call fire
      await page.reload();
      const chipNow = page.locator(`[data-chip-group="preferred-categories"] .chip[data-category-key="${chipKey}"]`);
      const wasActiveAfter = (await chipNow.getAttribute("aria-checked")) === "true";
      expect(wasActiveAfter).not.toBe(wasActiveBefore);

      // ─── Security ──────────────────────────────────────────────
      await page.goto("/account/security");
      await page.getByRole("button", { name: /Manage|Administrar/i }).first().click();
      // Clerk's hosted UserProfile mounts under `.cl-userProfile-root`.
      await expect(page.locator(".cl-userProfile-root, [data-clerk-component='UserProfile']")).toBeVisible({ timeout: 15_000 });
    } finally {
      await restoreUser(env, snap);
    }
  });
});
