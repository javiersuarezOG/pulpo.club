// Save-listing flow smoke test (PR-6 of the reliability plan).
//
// The audit flagged this as one of three "money path" e2e gaps —
// signup, save round-trip, Stripe checkout. Stripe checkout is already
// covered in start-funnel.spec.ts. This spec covers the save flow:
//
//   1. Anonymous user clicks heart → signup modal opens, listing NOT saved
//   2. Authenticated user clicks heart → optimistic UI flip +
//      localStorage `pulpo-saved` updated
//   3. Navigate to /saved → previously saved listing appears
//   4. Click heart again on /saved → unsaves, /saved becomes empty
//
// All against the dev server's Clerk-OFF surface (the path that
// localStorage-mode hits). The Clerk-ON path (/api/saves round-trip)
// would need a real publishable key and is intentionally out of scope
// for the public CI; the API contract is already pinned by the
// rate-limit unit tests in PR-3.

import { test, expect, type Page } from "@playwright/test";
import { attachErrorRecorder, seedUser } from "./_helpers";

// Set up the page state before navigation:
//   - dismiss the cookie consent banner (it sits over card clicks
//     and would block heart taps if we left it up)
//   - mock /api/saves so the FE's optional GET on hydration doesn't
//     hit the network (returns the expected empty-saves shape)
//   - mock /api/geo so the /start banner doesn't fight us
async function primePage(page: Page, opts: { initialSaves?: string[] } = {}) {
  await page.addInitScript(() => {
    try { localStorage.setItem("pulpo-cookie-consent", "accepted"); } catch {}
  });
  await page.route("**/api/geo**", (r) => r.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ country: "SV", currency: "USD" }),
  }));
  await page.route("**/api/saves**", (r) => r.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      saves: opts.initialSaves || [],
      cap: 10,
      plan: "free",
    }),
  }));
}

// /browse never settles into "networkidle" reliably under the Vite dev
// server (HMR ping + analytics keep the pipe warm). We wait on the
// actual signal we care about: the first listing card mounting.
async function gotoBrowse(page: Page) {
  await page.goto("/browse", { waitUntil: "domcontentloaded" });
  await page.locator(".listing-card").first().waitFor({
    state: "visible",
    timeout: 15_000,
  });
}

async function firstCardHeart(page: Page) {
  return page.locator(".listing-card").first().locator(".heart-btn").first();
}

async function readSavedFromLocalStorage(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    try {
      const raw = localStorage.getItem("pulpo-saved");
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });
}

test.describe("save-listing — anonymous user", () => {
  test("clicking the heart opens the signup modal and does NOT save", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await primePage(page);
    // Anonymous: explicitly clear any leftover user blob.
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch {}
      try { localStorage.removeItem("pulpo-saved"); } catch {}
    });

    await gotoBrowse(page);
    const heart = await firstCardHeart(page);
    await heart.click();

    // Modal shows up — .modal-signup (LegacySignupModal, Clerk-off
    // surface) or .modal-clerk-intro (Clerk-on dev). Either is fine
    // for this assertion: the contract is "anon click → modal opens".
    const modal = page.locator(".modal-signup, .modal-clerk-intro").first();
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // No save happened — the gating must run BEFORE toggleSave.
    const saved = await readSavedFromLocalStorage(page);
    expect(saved).toEqual([]);

    expect(errors, "anon save-click should not error").toEqual([]);
  });
});

test.describe("save-listing — authenticated user (Clerk-off / localStorage mode)", () => {
  test("heart → optimistic save → /saved shows the listing → unsave clears it", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await primePage(page);
    await seedUser(page, "free");

    await gotoBrowse(page);

    // ── Step 1: click heart on the first card ────────────────────
    const heart = await firstCardHeart(page);
    await expect(heart).not.toHaveClass(/is-saved/);
    await heart.click();
    await expect(heart).toHaveClass(/is-saved/, { timeout: 2_000 });

    const afterSave = await readSavedFromLocalStorage(page);
    expect(afterSave.length).toBeGreaterThan(0);
    const savedId = afterSave[0];

    // ── Step 2: navigate to /saved → listing appears ─────────────
    await page.goto("/saved", { waitUntil: "domcontentloaded" });
    const savedCards = page.locator(".listing-card");
    await expect(savedCards.first()).toBeVisible({ timeout: 5_000 });
    expect(await savedCards.count()).toBeGreaterThanOrEqual(1);

    // ── Step 3: unsave from /saved → page goes empty ─────────────
    const unsaveHeart = savedCards.first().locator(".heart-btn").first();
    await unsaveHeart.click();
    await expect(page.locator(".page-saved .empty-state")).toBeVisible({
      timeout: 5_000,
    });

    const afterUnsave = await readSavedFromLocalStorage(page);
    expect(afterUnsave).not.toContain(savedId);

    expect(errors, "save round-trip should not error").toEqual([]);
  });

  test("re-clicking the same heart removes the listing (idempotent toggle)", async ({ page }) => {
    // Pins the toggle semantic — a double-click ends back at "not saved",
    // not "saved twice". The app's optimistic update uses a Set, so a
    // future refactor that drops Set semantics would regress this.
    await primePage(page);
    await seedUser(page, "free");

    await gotoBrowse(page);
    const heart = await firstCardHeart(page);

    await heart.click();
    await expect(heart).toHaveClass(/is-saved/);
    expect((await readSavedFromLocalStorage(page)).length).toBe(1);

    await heart.click();
    await expect(heart).not.toHaveClass(/is-saved/);
    expect((await readSavedFromLocalStorage(page)).length).toBe(0);
  });
});
