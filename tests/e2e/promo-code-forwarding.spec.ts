// Wave-2 promo-code forwarding — end-to-end smoke.
//
// Flow under test: a free signed-in user lands at `/?code=PULPOFRIENDS`,
// navigates to `/plans` (URL no longer carries the code), clicks Upgrade.
// The POST to /api/stripe/create-checkout-session must carry the code
// (and UTMs) in its JSON body. campaign.ts's sessionStorage persistence
// is what keeps the code alive across the route change.
//
// We intercept the API request so the test doesn't actually hit Stripe —
// what we care about is the request body the FE built.
//
// Companion rollback test: same flow with `?ff_promo_code_forwarding_v2=0`
// forces the flag off; body should be empty `"{}"` (pre-Wave-2 behavior).

import { test, expect, type Page, type Route } from "@playwright/test";
import { attachErrorRecorder, seedUser } from "./_helpers";

type CapturedRequest = { url: string; body: string };

function attachCheckoutInterceptor(page: Page): { captured: CapturedRequest[] } {
  const captured: CapturedRequest[] = [];
  void page.route("**/api/stripe/create-checkout-session", async (route: Route) => {
    const req = route.request();
    captured.push({ url: req.url(), body: req.postData() ?? "" });
    // Return a fake Stripe URL so the FE's location.assign goes
    // somewhere benign; we'll intercept that next.
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ url: "about:blank?stripe_mock=1" }),
    });
  });
  // Block the subsequent navigation to about:blank?... so the test
  // can keep reading window state after the click.
  void page.route("**/about:blank*", (route) => route.abort());
  return { captured };
}

test.describe("Promo-code forwarding (Wave 2) — free user", () => {
  test("free user lands with ?code= → navigates to /plans → upgrade POSTs the code", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedUser(page, "free");
    const { captured } = attachCheckoutInterceptor(page);

    // Land on home with the campaign params. campaign.ts persists
    // code + utms to sessionStorage on first mount.
    await page.goto(
      "/?code=pulpofriends&utm_source=newsletter&utm_campaign=launch&ff_promo_code_forwarding_v2=1",
      { waitUntil: "networkidle" },
    );

    // Navigate to /plans via SPA route — URL no longer carries the code.
    await page.goto("/plans?ff_promo_code_forwarding_v2=1", { waitUntil: "networkidle" });
    expect(new URL(page.url()).searchParams.get("code")).toBeNull();

    // Click the Upgrade CTA on PlansPage (the Pro plan card).
    const upgradeCta = page.locator(".plan-card .btn-primary").first();
    await expect(upgradeCta).toBeVisible();
    await upgradeCta.click();

    // Poll briefly — the fetch fires synchronously but route handlers
    // resolve on the next tick.
    await expect.poll(() => captured.length, { timeout: 3_000 }).toBeGreaterThan(0);

    expect(captured).toHaveLength(1);
    const payload = JSON.parse(captured[0].body || "{}");
    expect(payload.promoCode).toBe("PULPOFRIENDS"); // uppercased
    expect(payload.utm_source).toBe("newsletter");
    expect(payload.utm_campaign).toBe("launch");

    expect(errors).toEqual([]);
  });

  test("flag forced OFF → body is empty (pre-Wave-2 behavior preserved for rollback)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedUser(page, "free");
    const { captured } = attachCheckoutInterceptor(page);

    await page.goto(
      "/?code=PULPOFRIENDS&utm_source=newsletter&ff_promo_code_forwarding_v2=0",
      { waitUntil: "networkidle" },
    );
    await page.goto("/plans?ff_promo_code_forwarding_v2=0", { waitUntil: "networkidle" });

    const upgradeCta = page.locator(".plan-card .btn-primary").first();
    await upgradeCta.click();

    await expect.poll(() => captured.length, { timeout: 3_000 }).toBeGreaterThan(0);

    // With the kill switch engaged, the body is the pre-Wave-2 literal "{}".
    expect(captured[0].body).toBe("{}");

    expect(errors).toEqual([]);
  });

  test("free user without a code → empty payload (regression guard)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedUser(page, "free");
    const { captured } = attachCheckoutInterceptor(page);

    await page.goto("/plans?ff_promo_code_forwarding_v2=1", { waitUntil: "networkidle" });

    const upgradeCta = page.locator(".plan-card .btn-primary").first();
    await upgradeCta.click();

    await expect.poll(() => captured.length, { timeout: 3_000 }).toBeGreaterThan(0);

    // No code, no UTMs in URL or sessionStorage → body has no promoCode key
    // (may still be "{}" or contain other params). Assert promoCode is
    // absent rather than asserting exact body string.
    const payload = JSON.parse(captured[0].body || "{}");
    expect(payload.promoCode).toBeUndefined();

    expect(errors).toEqual([]);
  });
});
