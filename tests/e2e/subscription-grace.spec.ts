// End-to-end coverage for the 14-day grace window after a failed
// payment.
//
// Scenarios:
//  1. past_due user within grace → Pro identity STILL visible
//     (header pill + ring + ★, BottomNav star), plus the warning
//     banner on /account/subscription with "X days left"
//     copy.
//  2. past_due user PAST grace → Pro identity gone (effective free),
//     the "expired" banner shows on Account with a Reactivate CTA.
//  3. Active Pro user → no banner, regular Pro identity.
//
// Driven by the legacy localStorage seed because CI runs Clerk OFF.
// The same hydration path applies subscription_status / grace fields
// on the Clerk path (clerk-bundle.jsx) — unit-tested in
// web/app/lib/subscription.test.ts.

import { test, expect, type Page } from "@playwright/test";
import {
  attachErrorRecorder,
  seedCanceledUser,
  seedCancelingUser,
  seedPastDueUser,
  seedProUser,
  seedUser,
} from "./_helpers";

async function gotoAccountSubscription(page: Page, suffix = "") {
  await page.goto(`/account/subscription${suffix}`, {
    waitUntil: "domcontentloaded",
  });
}

test.describe("Subscription grace window — 14 days after a failed payment", () => {
  test("past_due within grace: Pro identity stays + warning banner appears", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedPastDueUser(page, { failedDaysAgo: 3 });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    // Pro identity still rendered — user is mid-grace, treat as Pro.
    await expect(page.getByTestId("avatar-pro")).toBeVisible();
    await expect(page.locator(".avatar-pro-badge")).toBeVisible();
    await expect(page.locator(".pulpo-logo-pro")).toBeVisible();

    await gotoAccountSubscription(page);

    // The warning banner is rendered with "days left" copy that
    // mentions the calendar date as well. We assert structure, not
    // exact wording, so a future copy tweak doesn't break the test.
    const banner = page.getByTestId("sub-grace-banner");
    await expect(banner).toBeVisible();
    // 10 or 11 days — `failedDaysAgo: 3` puts the boundary at exactly
    // 11d remaining, but Math.floor on `now - failed_at` slides to 10d
    // a fraction of a second after the page boots. Accept either, in
    // EN ("days") or ES ("días"). Don't pin the surrounding wording.
    await expect(banner).toContainText(/1[01] /);
    await expect(banner).toContainText(/days|días/);
    // CTA bounces to Stripe portal; we just assert it's wired.
    await expect(page.getByTestId("sub-grace-banner-cta")).toBeVisible();
    // Expired banner is NOT shown.
    await expect(page.getByTestId("sub-grace-banner-expired")).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test("past_due AFTER grace expires: Pro identity gone + expired banner with reactivate CTA", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedPastDueUser(page, { failedDaysAgo: 20 });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    // Effective plan is now "free" — Pro identity should NOT render.
    await expect(page.getByTestId("avatar-pro")).toHaveCount(0);
    await expect(page.locator(".avatar-pro-badge")).toHaveCount(0);
    await expect(page.locator(".pulpo-logo-pro")).toHaveCount(0);

    await gotoAccountSubscription(page);

    // Expired banner is shown.
    const expired = page.getByTestId("sub-grace-banner-expired");
    await expect(expired).toBeVisible();
    await expect(page.getByTestId("sub-grace-banner-reactivate-cta")).toBeVisible();
    // The "within grace" banner should NOT also render.
    await expect(page.getByTestId("sub-grace-banner")).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test("active Pro user: no banner anywhere", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);
    await gotoAccountSubscription(page);

    await expect(page.getByTestId("sub-grace-banner")).toHaveCount(0);
    await expect(page.getByTestId("sub-grace-banner-expired")).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test("Pro user: subscription card shows 'Pulpo Pro' label + gold pill (parity with header)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);
    await gotoAccountSubscription(page);

    // The plan-name container renders the brand mark — "Pulpo" + the
    // canonical .pulpo-logo-pro span — when the user is on Pro.
    const planName = page.locator(".sub-plan-name");
    await expect(planName).toBeVisible();
    await expect(planName).toContainText("Pulpo");
    // The exact same gold pill the SiteHeader uses, nested inside the
    // subscription card. We assert presence + correct text rather than
    // a positional locator so a future copy tweak in EN/ES doesn't
    // break the test (the brand mark "Pro" itself is locale-neutral).
    const proPill = planName.locator(".pulpo-logo-pro");
    await expect(proPill).toBeVisible();
    await expect(proPill).toHaveText(/^Pro$/);
    // Regression guard against the prior "Pulpo Monthly" copy — make
    // sure that legacy string doesn't sneak back in here.
    await expect(planName).not.toContainText(/Pulpo Monthly/);

    expect(errors).toEqual([]);
  });

  test("Free user: subscription card shows 'Free' label, no Pro pill", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedUser(page, "free");
    await gotoAccountSubscription(page);

    const planName = page.locator(".sub-plan-name");
    await expect(planName).toBeVisible();
    await expect(planName).toContainText("Free");
    await expect(planName.locator(".pulpo-logo-pro")).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test("canceling user: EN and ES copy says cancellation, never renewal", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedCancelingUser(page);
    await gotoAccountSubscription(page);

    await expect(page.locator(".sub-plan-meta")).toContainText(/Cancels on/i);
    await expect(page.locator(".sub-plan-status-copy")).toContainText(/stays active until/i);
    await expect(page.getByTestId("sub-status-pill")).toHaveText(/Canceling/i);
    await expect(page.locator(".account-section")).not.toContainText(/Renews on/i);

    await gotoAccountSubscription(page, "?lang=es");
    await expect(page.locator(".sub-plan-meta")).toContainText(/Se cancela/i);
    await expect(page.locator(".sub-plan-status-copy")).toContainText(/permanece activo hasta/i);
    await expect(page.getByTestId("sub-status-pill")).toHaveText(/Cancelando/i);
    await expect(page.locator(".account-section")).not.toContainText(/Se renueva/i);

    expect(errors).toEqual([]);
  });

  test("canceled user: EN and ES copy shows ended state + resubscribe CTA", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedCanceledUser(page);
    await gotoAccountSubscription(page);

    await expect(page.locator(".sub-plan-meta")).toContainText(/Subscription ended on/i);
    await expect(page.getByTestId("sub-status-pill")).toHaveText(/Canceled/i);
    await expect(page.getByRole("button", { name: /Resubscribe/i })).toBeVisible();
    await expect(page.locator(".account-section")).not.toContainText(/Renews on/i);

    await gotoAccountSubscription(page, "?lang=es");
    await expect(page.locator(".sub-plan-meta")).toContainText(/Suscripción finalizada el/i);
    await expect(page.getByTestId("sub-status-pill")).toHaveText(/Cancelada/i);
    await expect(page.getByRole("button", { name: /Volver a suscribirme/i })).toBeVisible();
    await expect(page.locator(".account-section")).not.toContainText(/Se renueva/i);

    expect(errors).toEqual([]);
  });

  test("portal return strips URL flag and emits return telemetry", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedCancelingUser(page);
    await gotoAccountSubscription(page, "?from=portal&posthog_capture=1");

    await expect.poll(() => page.url()).not.toContain("from=portal");
    await expect.poll(async () => page.evaluate(() => {
      const w = window as unknown as { __pulpoEvents__?: Array<{ name: string }> };
      return (w.__pulpoEvents__ || []).filter((e) => e.name === "account.sub_portal_return").length;
    })).toBe(1);

    expect(errors).toEqual([]);
  });
});
