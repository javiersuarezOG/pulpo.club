// Wave-1 CTA routing — end-to-end smoke for the three user states.
// Covers the bleeding-bug fixes:
//   * Paid user no longer gets a signup modal from the hero CTA.
//   * Free user lands on /plans (the per-CTA paywall surface) instead
//     of a signup modal on a Pro-gated click.
//   * Anonymous user routes to /start (the email-collect Stripe entry)
//     instead of a signup-modal intermediary.
//
// Mechanism: `?posthog_capture=1` pushes every track() call to
// window.__pulpoEvents__ so the spec can assert which branch fired
// without needing PostHog network round-trips. Same pattern as
// posthog-events.spec.ts.
//
// `?ff_cta_routing_v2=1` forces the feature flag on (covers the case
// where PostHog hasn't loaded by the time the click fires — in test
// mode there's no posthog network round-trip).

import { test, expect, type Page } from "@playwright/test";
import { attachErrorRecorder, seedUser, seedProUser } from "./_helpers";

type CapturedEvent = { name: string; props: Record<string, unknown>; ts: number };

const URL_HOME = "/?posthog_capture=1&ff_cta_routing_v2=1";

async function getEvents(page: Page): Promise<CapturedEvent[]> {
  return page.evaluate(() => {
    const w = window as unknown as { __pulpoEvents__?: CapturedEvent[] };
    return Array.isArray(w.__pulpoEvents__) ? [...w.__pulpoEvents__] : [];
  });
}

function findCtaRouted(events: CapturedEvent[], ctaId: string) {
  return events.find(
    (e) => e.name === "cta_routed" && e.props.cta_id === ctaId,
  );
}

test.describe("CTA routing (Wave 1) — hero primary CTA branches per user state", () => {
  test("anonymous user → cta_routed branch is stripe_checkout (routes to /start)", async ({ page, context }) => {
    const errors = attachErrorRecorder(page);

    // Intercept the /start redirect so we don't navigate away mid-test;
    // the event we care about has already fired by the time
    // location.assign is called.
    await context.route("**/start**", (route) => {
      void route.fulfill({ status: 204, body: "" });
    });

    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    const heroCta = page.locator('button.hp-hero-cta-primary');
    await expect(heroCta).toBeVisible();
    await heroCta.click();
    await page.waitForTimeout(150);

    const ev = findCtaRouted(await getEvents(page), "hero_primary");
    expect(ev, "cta_routed should fire on hero primary click").toBeTruthy();
    expect(ev!.props.user_state).toBe("anonymous");
    expect(ev!.props.branch).toBe("stripe_checkout");
    expect(ev!.props.flag_enabled).toBe(true);

    expect(errors).toEqual([]);
  });

  test("free user → cta_routed branch is paywall (lands on /plans)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedUser(page, "free");

    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    const heroCta = page.locator('button.hp-hero-cta-primary');
    await expect(heroCta).toBeVisible();
    await heroCta.click();

    await expect.poll(
      async () => (findCtaRouted(await getEvents(page), "hero_primary") || {}).props?.branch,
      { timeout: 3_000, message: "expected cta_routed branch=paywall for free user" },
    ).toBe("paywall");

    const ev = findCtaRouted(await getEvents(page), "hero_primary")!;
    expect(ev.props.user_state).toBe("free");

    // Free user should land on /plans (the central paywall dispatch).
    await page.waitForURL(/\/plans/, { timeout: 3_000 });

    expect(errors).toEqual([]);
  });

  test("pro user → cta_routed branch is passthrough; no signup modal, URL stays on /", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);

    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    const heroCta = page.locator('button.hp-hero-cta-primary');
    // Paid users may not see this CTA in Wave 4. In Wave 1 it's still
    // rendered but a click is a no-op.
    if (!(await heroCta.isVisible().catch(() => false))) {
      test.skip(true, "hero CTA not present for pro user — Wave 4 hides it");
    }
    await heroCta.click();
    await page.waitForTimeout(150);

    const ev = findCtaRouted(await getEvents(page), "hero_primary");
    expect(ev, "cta_routed should still fire for pro user (telemetry on no-op)").toBeTruthy();
    expect(ev!.props.user_state).toBe("pro");
    expect(ev!.props.branch).toBe("passthrough");

    // No signup modal — the bug we're fixing. The modal renders a
    // .modal-signup node in the DOM; assert it's NOT present.
    await expect(page.locator(".modal-signup")).toHaveCount(0);

    // URL must stay on home.
    expect(new URL(page.url()).pathname).toBe("/");

    expect(errors).toEqual([]);
  });
});

test.describe("CTA routing (Wave 1) — FeaturedDeal no longer opens signup for paid users", () => {
  test("pro user clicking FeaturedDeal fires cta_routed=passthrough with no signup modal", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);

    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    // FeaturedDeal card click — clickable anywhere on the article.
    const card = page.locator(".hp-featured-card").first();
    if (!(await card.isVisible().catch(() => false))) {
      test.skip(true, "FeaturedDeal not rendered for pro user — Wave 4 hides it");
    }
    await card.click();
    await page.waitForTimeout(150);

    const ev = findCtaRouted(await getEvents(page), "featured_deal");
    expect(ev, "cta_routed should fire for FeaturedDeal click").toBeTruthy();
    expect(ev!.props.user_state).toBe("pro");
    expect(ev!.props.branch).toBe("passthrough");

    await expect(page.locator(".modal-signup")).toHaveCount(0);

    expect(errors).toEqual([]);
  });
});

test.describe("CTA routing (Wave 1) — rollback flag", () => {
  test("anon user with cta_routing_v2 forced OFF falls back to old behavior (signup modal opens)", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto("/?posthog_capture=1&ff_cta_routing_v2=0", { waitUntil: "networkidle" });

    const heroCta = page.locator('button.hp-hero-cta-primary');
    await heroCta.click();
    await page.waitForTimeout(150);

    // Rollback path runs `app.openSignup({ mode: "signup" })` directly;
    // cta_routed does NOT fire because the flag short-circuit returns
    // before the routing call.
    const events = await getEvents(page);
    expect(
      findCtaRouted(events, "hero_primary"),
      "cta_routed must NOT fire when the kill-switch is engaged",
    ).toBeUndefined();

    // Old behavior: signup modal appears.
    await expect(page.locator(".modal-signup")).toBeVisible();

    expect(errors).toEqual([]);
  });
});
