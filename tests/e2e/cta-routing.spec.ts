// CTA routing — end-to-end smoke for the three user states.
//
// Post-#262 contract:
//   * Paid user: hero CTA passthrough → no-op (no modal). Unchanged.
//   * Anon + free: hero / header / featured / shelf / favorites CTAs
//     all route to `free_month_modal` → FreeMonthModal opens in-page
//     (no /start or /plans navigation).
//   * Wave-1 rollback path (ff_cta_routing_v2=0) still falls back to
//     app.openSignup() for anon, unchanged.
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

// Hero v4 is the default-on visual in production. These CTA-routing
// tests target selectors on the legacy HeroV2 surface (.hp-hero /
// .hp-hero-cta-primary etc.), so opt out of v4 here. CTA-routing
// behavior is identical across hero versions; v4 coverage of the
// same flows lives in tests/e2e/hero-v4.spec.ts.
const URL_HOME = "/?posthog_capture=1&ff_cta_routing_v2=1&ff_hero_v4=0";

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

test.describe("CTA routing — hero primary CTA branches per user state", () => {
  test("anonymous user → cta_routed branch=free_month_modal; FreeMonthModal opens", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    const heroCta = page.locator('button.hp-hero-cta-primary');
    await expect(heroCta).toBeVisible();
    await heroCta.click();
    await page.waitForTimeout(150);

    const ev = findCtaRouted(await getEvents(page), "hero_primary");
    expect(ev, "cta_routed should fire on hero primary click").toBeTruthy();
    expect(ev!.props.user_state).toBe("anonymous");
    expect(ev!.props.branch).toBe("free_month_modal");
    expect(ev!.props.flag_enabled).toBe(true);

    // The post-#262 contract: clicking the hero CTA opens the in-page
    // FreeMonthModal instead of navigating to /start. URL stays on /.
    await expect(page.locator(".free-month-modal")).toBeVisible({ timeout: 3_000 });
    expect(new URL(page.url()).pathname).toBe("/");

    expect(errors).toEqual([]);
  });

  test("free user → cta_routed branch=free_month_modal; FreeMonthModal opens (no /plans nav)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedUser(page, "free");

    await page.goto(URL_HOME, { waitUntil: "networkidle" });

    const heroCta = page.locator('button.hp-hero-cta-primary');
    await expect(heroCta).toBeVisible();
    await heroCta.click();

    await expect.poll(
      async () => (findCtaRouted(await getEvents(page), "hero_primary") || {}).props?.branch,
      { timeout: 3_000, message: "expected cta_routed branch=free_month_modal for free user" },
    ).toBe("free_month_modal");

    const ev = findCtaRouted(await getEvents(page), "hero_primary")!;
    expect(ev.props.user_state).toBe("free");

    // Post-#262: free users get the modal too (no /plans navigation).
    await expect(page.locator(".free-month-modal")).toBeVisible({ timeout: 3_000 });
    expect(new URL(page.url()).pathname).toBe("/");

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

    await page.goto("/?posthog_capture=1&ff_cta_routing_v2=0&ff_hero_v4=0", { waitUntil: "networkidle" });

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
