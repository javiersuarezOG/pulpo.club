// End-to-end regression for the founder-email Pro override.
//
// The scenarios:
//   1. A localStorage user with plan="free" and email in
//      VITE_FOUNDER_EMAILS gets promoted to Pro on hydration —
//      verified by SiteHeader rendering the Pro identity chrome.
//   2. The Pro identity is consistent across home / browse / saved /
//      account / plans (every route mounts SiteHeader).
//   3. Mobile parity: at the BottomNav-active viewports the Profile
//      tab carries the ★ Pro badge. At 320px the wordmark pill is
//      hidden by design but the avatar ring + star remain.
//   4. The Plans page renders "Your plan" (disabled) for Pro users
//      instead of the "Upgrade — €10/month" re-checkout CTA.
//
// Driven by the legacy auth path (localStorage seed) since Playwright
// CI runs with Clerk off. The same hydration helper applies the
// override on the Clerk path (clerk-bundle.jsx) — tested at the unit
// level in web/app/lib/founder-emails.test.ts.

import { test, expect, type Page } from "@playwright/test";
import { attachErrorRecorder, seedFounderUser, seedUser } from "./_helpers";

async function assertProHeader(page: Page): Promise<void> {
  // Pro pill on the wordmark (hidden below 360px — caller picks the
  // viewport before calling).
  // Gold-ring avatar always renders for Pro.
  await expect(page.getByTestId("avatar-pro")).toBeVisible();
  // ★ badge on the avatar.
  await expect(page.locator(".avatar-pro-badge")).toBeVisible();
}

test.describe("Founder-email Pro override — full Pro identity across the app", () => {
  test("home: free-plan user with founder email hydrates as Pro", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedFounderUser(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await assertProHeader(page);
    // Wordmark pill present at desktop viewport (default 1280×720).
    await expect(page.locator(".pulpo-logo-pro")).toBeVisible();
    await expect(page.locator(".pulpo-logo-pro")).toHaveText(/^Pro$/);
    expect(errors).toEqual([]);
  });

  test("Pro identity persists across all main routes", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedFounderUser(page);
    for (const path of ["/", "/browse", "/saved", "/plans", "/account"]) {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      await expect(page.getByTestId("avatar-pro"), `avatar-pro on ${path}`).toBeVisible();
      await expect(page.locator(".avatar-pro-badge"), `badge on ${path}`).toBeVisible();
    }
    expect(errors).toEqual([]);
  });

  test("mobile (375px): BottomNav profile tab carries the Pro star", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await seedFounderUser(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    // Avatar ring + star still present in the top-nav (mobile keeps
    // both — only the wordmark pill drops below 360px).
    await expect(page.getByTestId("avatar-pro")).toBeVisible();
    await expect(page.locator(".avatar-pro-badge")).toBeVisible();
    // BottomNav profile tab has the new ★ badge.
    await expect(page.getByTestId("bottomnav-profile-pro")).toBeVisible();
    await expect(page.locator(".bottomnav .tab-pro-badge")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("320px: wordmark pill hidden, avatar ring + star + bottomnav star still visible", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.setViewportSize({ width: 320, height: 568 });
    await seedFounderUser(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    // Pill is display:none below 360px — assert it's hidden, not absent.
    // Locating + isVisible() is the right idiom: the DOM node exists but
    // the bounding box is 0×0.
    const pill = page.locator(".pulpo-logo-pro");
    await expect(pill).toBeAttached();
    await expect(pill).toBeHidden();
    // Durable signals: avatar ring + ★, plus the BottomNav star.
    await expect(page.locator(".avatar-pro-badge")).toBeVisible();
    await expect(page.locator(".bottomnav .tab-pro-badge")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("plans page: Pro user sees 'Your plan' (disabled), not re-checkout CTA", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedFounderUser(page);
    await page.goto("/plans", { waitUntil: "domcontentloaded" });
    // The Pro card swaps the upgrade CTA for a disabled "Your plan"
    // button — tagged with data-testid for stable lookup.
    const currentCta = page.getByTestId("plan-pro-current-cta");
    await expect(currentCta).toBeVisible();
    await expect(currentCta).toBeDisabled();
    // The card itself carries the .plan-card-current marker so future
    // visual diffs catch a theming regression.
    await expect(page.getByTestId("plan-card-pro")).toHaveClass(/plan-card-current/);
    // No "Upgrade — €" button anywhere on the page for a Pro viewer.
    await expect(page.getByRole("button", { name: /Upgrade — €/ })).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("non-founder free user does NOT get promoted (regression guard)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedUser(page, "free");
    await page.goto("/", { waitUntil: "domcontentloaded" });
    // Free user: no Pro identity anywhere.
    await expect(page.getByTestId("avatar-pro")).toHaveCount(0);
    await expect(page.locator(".pulpo-logo-pro")).toHaveCount(0);
    await expect(page.locator(".avatar-pro-badge")).toHaveCount(0);
    // Plans page still shows the upgrade CTA.
    await page.goto("/plans", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("button", { name: /Upgrade — €/ })).toBeVisible();
    expect(errors).toEqual([]);
  });
});
