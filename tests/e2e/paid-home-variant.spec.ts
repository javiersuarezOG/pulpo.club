// Wave-4 paid-home variant — end-to-end smoke for the block registry.
//
// Three scenarios:
//   1. Pro user + flag on → upsell blocks (hero, featured, usps) NOT
//      in the DOM. Carousels still present.
//   2. Pro user + flag off → all 7 blocks visible (rollback path
//      preserves today's behavior byte-for-byte).
//   3. Free user + flag on → all 7 blocks visible (filter targets
//      paid only; free users see the same homepage).
//
// Mechanism: `?ff_paid_home_variant_v1=1/0` forces the flag locally,
// same URL-override pattern Wave 1 uses for cta_routing_v2.

import { test, expect, type Page } from "@playwright/test";
import { attachErrorRecorder, seedUser, seedProUser } from "./_helpers";

type CapturedEvent = { name: string; props: Record<string, unknown>; ts: number };

async function getEvents(page: Page): Promise<CapturedEvent[]> {
  return page.evaluate(() => {
    const w = window as unknown as { __pulpoEvents__?: CapturedEvent[] };
    return Array.isArray(w.__pulpoEvents__) ? [...w.__pulpoEvents__] : [];
  });
}

test.describe("Paid-home variant (Wave 4) — block registry filtering", () => {
  test("pro user + flag on: featured/usps/shoreline suppressed, hero image + shelves visible", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);

    await page.goto(
      "/?posthog_capture=1&ff_paid_home_variant_v1=1",
      { waitUntil: "networkidle" },
    );

    // Post-#262: paid users see the hero image (CTA + microcopy gated
    // in the component). featured + usps + shoreline are NON_PAID and
    // don't mount.
    await expect(page.locator(".hp-hero, .hp-hero-v4")).toBeVisible();
    await expect(page.locator(".hp-featured")).toHaveCount(0);
    await expect(page.locator(".hp-usp")).toHaveCount(0);
    await expect(page.locator(".hp-shoreline")).toHaveCount(0);

    // Carousel surfaces remain. Note: under hero_v4 each shelf requires
    // at least 5 qualifying listings; price_drops can render null when
    // the catalog has too few repriced listings to surface. The block
    // registry still emits it (asserted via blocks_visible below) — the
    // DOM presence is data-gated.
    await expect(page.locator("#hp-shelf-top10")).toBeVisible();
    await expect(page.locator("#hp-shelf-new")).toBeVisible();

    // paid_home_rendered fires with the trimmed list.
    const ev = (await getEvents(page)).find((e) => e.name === "paid_home_rendered");
    expect(ev, "paid_home_rendered should fire on mount").toBeTruthy();
    expect(ev!.props.user_state).toBe("pro");
    expect(ev!.props.flag_enabled).toBe(true);
    expect(ev!.props.blocks_visible).toEqual([
      "hero", "top_10", "price_drops", "new_this_week",
    ]);

    expect(errors).toEqual([]);
  });

  test("pro user + flag off: all 7 blocks visible (rollback path)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);

    await page.goto(
      "/?posthog_capture=1&ff_paid_home_variant_v1=0&ff_hero_v4=0",
      { waitUntil: "networkidle" },
    );

    // Pre-Wave-4 behavior: every block visible, even for pro.
    await expect(page.locator(".hp-hero")).toBeVisible();
    await expect(page.locator(".hp-featured")).toBeVisible();
    await expect(page.locator(".hp-usp")).toBeVisible();
    await expect(page.locator(".hp-shoreline")).toBeVisible();
    await expect(page.locator("#hp-shelf-top10")).toBeVisible();

    const ev = (await getEvents(page)).find((e) => e.name === "paid_home_rendered");
    expect(ev).toBeTruthy();
    expect(ev!.props.flag_enabled).toBe(false);
    expect((ev!.props.blocks_visible as string[]).length).toBe(7);

    expect(errors).toEqual([]);
  });

  test("free user + flag on: filter is paid-only, free sees everything", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedUser(page, "free");

    await page.goto(
      "/?posthog_capture=1&ff_paid_home_variant_v1=1&ff_hero_v4=0",
      { waitUntil: "networkidle" },
    );

    await expect(page.locator(".hp-hero")).toBeVisible();
    await expect(page.locator(".hp-featured")).toBeVisible();
    await expect(page.locator(".hp-usp")).toBeVisible();

    const ev = (await getEvents(page)).find((e) => e.name === "paid_home_rendered");
    expect(ev).toBeTruthy();
    expect(ev!.props.user_state).toBe("free");
    expect((ev!.props.blocks_visible as string[]).length).toBe(7);

    expect(errors).toEqual([]);
  });
});
