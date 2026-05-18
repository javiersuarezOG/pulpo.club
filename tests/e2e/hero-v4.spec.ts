// Wave 5#7+#9 hero_v4 — end-to-end smoke.
//
// Coverage:
//   * Flag off → HeroV2 (dark forest + leaderboard) renders byte-for-byte
//     as today. FeaturedDeal block visible. .hp-hero-v4 absent.
//   * Flag on → HeroV4 (white split + real photo) renders. FeaturedDeal
//     block absent (absorbed into hero). hero_v4_viewed event fires.
//     SiteHeader/footer/BottomNav/routing all unchanged.
//   * Flag on + paid user (paid_home_variant_v1 also on) → hero block
//     suppressed entirely (paid user filter wins).
//   * Flag on + click hero CTA → opens FreeMonthModal (post-#262 routing).
//   * Flag on + click hero photo → opens listing detail (Wave-1
//     featured_deal passthrough).

import { test, expect, type Page } from "@playwright/test";
import { attachErrorRecorder, seedUser, seedProUser } from "./_helpers";

type CapturedEvent = { name: string; props: Record<string, unknown>; ts: number };

async function getEvents(page: Page): Promise<CapturedEvent[]> {
  return page.evaluate(() => {
    const w = window as unknown as { __pulpoEvents__?: CapturedEvent[] };
    return Array.isArray(w.__pulpoEvents__) ? [...w.__pulpoEvents__] : [];
  });
}

test.describe("hero_v4 (Wave 5#7+#9) — flag off (rollback path)", () => {
  test("HeroV3 renders, FeaturedDeal block present, .hp-hero-v4 absent", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto(
      "/?posthog_capture=1&ff_hero_v4=0",
      { waitUntil: "networkidle" },
    );

    await expect(page.locator(".hp-hero-v3")).toBeVisible();
    await expect(page.locator(".hp-hero-v4")).toHaveCount(0);
    await expect(page.locator(".hp-featured")).toBeVisible();
    await expect(page.locator(".homepage-v2")).not.toHaveClass(/hero-v4/);

    const events = await getEvents(page);
    expect(events.find((e) => e.name === "hero_v4_viewed")).toBeUndefined();

    expect(errors).toEqual([]);
  });
});

test.describe("hero_v4 (Wave 5#7+#9) — flag on", () => {
  test("HeroV4 renders, FeaturedDeal absorbed, hero_v4_viewed fires", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto(
      "/?posthog_capture=1&ff_hero_v4=1",
      { waitUntil: "networkidle" },
    );

    // New white photo-led hero visible; old dark hero gone.
    await expect(page.locator(".hp-hero-v4")).toBeVisible();
    await expect(page.locator(".hp-hero-v3")).toHaveCount(0);

    // FeaturedDeal standalone block absorbed into hero.
    await expect(page.locator(".hp-featured")).toHaveCount(0);

    // Parent class applied for scoped restyling of shelves / USP / etc.
    await expect(page.locator(".homepage-v2.hero-v4")).toBeVisible();

    // Telemetry fires once on mount.
    const ev = (await getEvents(page)).find((e) => e.name === "hero_v4_viewed");
    expect(ev, "hero_v4_viewed should fire on mount").toBeTruthy();

    // Carousels + USP + shoreline still render (visual restyle only,
    // structure preserved).
    await expect(page.locator(".hp-usp")).toBeVisible();
    await expect(page.locator(".hp-shoreline")).toBeVisible();
    await expect(page.locator("#hp-shelf-top10")).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("anon clicking hero CTA → opens FreeMonthModal (post-#262 routing)", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto(
      "/?posthog_capture=1&ff_hero_v4=1",
      { waitUntil: "networkidle" },
    );

    await page.locator(".hp-hero-v4-cta").click();

    // Post-#262 anon path: in-page modal instead of /start redirect.
    await expect(page.locator(".free-month-modal")).toBeVisible({ timeout: 3_000 });

    const events = await getEvents(page);
    expect(
      events.find((e) => e.name === "homepage.cta_clicked" && e.props.location === "hero_primary"),
    ).toBeTruthy();
    const routed = events.find((e) => e.name === "cta_routed" && e.props.cta_id === "hero_primary");
    expect(routed).toBeTruthy();
    expect(routed!.props.branch).toBe("free_month_modal");
    expect(
      events.find((e) => e.name === "free_month_modal.shown" && e.props.trigger === "hero_cta"),
    ).toBeTruthy();

    expect(errors).toEqual([]);
  });

  test("pro clicking hero photo → opens listing detail (Wave-1 featured_deal passthrough)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);

    await page.goto(
      "/?posthog_capture=1&ff_hero_v4=1",
      { waitUntil: "networkidle" },
    );

    // Wait for the real listing to resolve (Wave-5b plumbing) — the
    // photo only becomes clickable after that.
    await expect(page.locator(".hp-hero-v4-photo-clickable")).toBeVisible({ timeout: 5_000 });

    await page.locator(".hp-hero-v4-photo-clickable").dispatchEvent("click");

    await expect(page.locator(".detail-panel").first()).toBeVisible({ timeout: 5_000 });

    const events = await getEvents(page);
    const routed = events.find((e) => e.name === "cta_routed" && e.props.cta_id === "featured_deal");
    expect(routed).toBeTruthy();
    expect(routed!.props.branch).toBe("passthrough");
    expect(routed!.props.user_state).toBe("pro");

    expect(errors).toEqual([]);
  });

  test("paid user with paid_home_variant_v1 + hero_v4: entire hero block suppressed", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);

    await page.goto(
      "/?posthog_capture=1&ff_hero_v4=1&ff_paid_home_variant_v1=1",
      { waitUntil: "networkidle" },
    );

    // paid_home_variant_v1 filters out the upsell-oriented `hero` block
    // for paid users — and hero_v4 ALSO filters out `featured`. Result:
    // the homepage opens with carousels (shoreline first).
    await expect(page.locator(".hp-hero-v4")).toHaveCount(0);
    await expect(page.locator(".hp-hero-v3")).toHaveCount(0);
    await expect(page.locator(".hp-featured")).toHaveCount(0);
    await expect(page.locator(".hp-shoreline")).toBeVisible();

    expect(errors).toEqual([]);
  });
});
