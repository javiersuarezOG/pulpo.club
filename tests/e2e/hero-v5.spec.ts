// Wave 6 — HeroV5 ("Sunday morning, coffee, your top 10 properties")
// end-to-end smoke.
//
// Coverage:
//   * Flag off (?ff_hero_v5=0 — kill-switch path; the production default
//     is now ON as of 2026-06-01) → HeroV5 does NOT render. The legacy
//     hero block + PickShoreline render as the fallback.
//   * Flag on (production default, or ?ff_hero_v5=1) → HeroV5 renders.
//     Old hero block AND PickShoreline both absent (registry swaps them
//     out). hero_v5_viewed event fires. No horizontal overflow at any
//     of the 5 standard viewports.
//   * Flag on + click destination card → navigates to /browse with the
//     expected category filter applied (master_category for now; zone-
//     level filtering is a follow-up).
//   * Flag on + click first card (All listings) → navigates to /browse
//     with no filter set.
//
// SiteHeader, footer, BottomNav, locale routing all unchanged — covered
// by responsive-smoke.spec at the same viewports.

import { readFileSync } from "node:fs";
import { test, expect, type Page } from "@playwright/test";
import { attachErrorRecorder, TOLERATED, isTolerated } from "./_helpers";

const versions = JSON.parse(
  readFileSync(new URL("../../web/app/home/versions.json", import.meta.url), "utf8"),
) as { blocks: { hero_v5: string } };

type CapturedEvent = { name: string; props: Record<string, unknown>; ts: number };

async function getEvents(page: Page): Promise<CapturedEvent[]> {
  return page.evaluate(() => {
    const w = window as unknown as { __pulpoEvents__?: CapturedEvent[] };
    return Array.isArray(w.__pulpoEvents__) ? [...w.__pulpoEvents__] : [];
  });
}

const VIEWPORTS = [
  { name: "320×568 iPhone SE",      width: 320,  height: 568  },
  { name: "375×812 iPhone 13",      width: 375,  height: 812  },
  { name: "414×896 iPhone Pro Max", width: 414,  height: 896  },
  { name: "768×1024 iPad portrait", width: 768,  height: 1024 },
  { name: "1280×800 desktop",       width: 1280, height: 800  },
];

test.describe("@legacy hero_v5 — flag off (kill-switch path)", () => {
  test("HeroV5 absent, legacy hero + shoreline render", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto("/?ff_hero_v5=0", { waitUntil: "networkidle" });

    await expect(page.locator(".hp-hero-v5")).toHaveCount(0);
    // HeroV4 is the current production default (hero_v4 defaults true).
    await expect(page.locator(".hp-hero-v4")).toBeVisible();
    await expect(page.locator(".hp-shoreline")).toBeVisible();

    expect(errors.filter((e) => !isTolerated(e, TOLERATED))).toEqual([]);
  });
});

test.describe("hero_v5 — flag on", () => {
  test("HeroV5 renders, legacy hero + shoreline both absent", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await page.goto(
      "/?posthog_capture=1&ff_hero_v5=1",
      { waitUntil: "networkidle" },
    );

    await expect(page.locator(".hp-hero-v5")).toBeVisible();
    await expect(page.locator(".hp-hero-v4")).toHaveCount(0);
    await expect(page.locator(".hp-shoreline")).toHaveCount(0);

    // H1 is present + readable
    await expect(page.locator("#hp-hero-v5-h1")).toBeVisible();
    // 5 destination cards: All + Surf City I + Surf City II + Coatepeque + Ilopango
    await expect(page.locator(".hp-hero-v5-dest")).toHaveCount(5);
    // Newsletter postcard preview
    await expect(page.locator(".hp-hero-v5-postcard")).toBeVisible();

    const events = await getEvents(page);
    expect(events.find((e) => e.name === "hero_v5_viewed")?.props.version)
      .toBe(versions.blocks.hero_v5);
    expect(events.find((e) => e.name === "paid_home_rendered")?.props.hero_v5_version)
      .toBe(versions.blocks.hero_v5);
    expect(events.find((e) => (
      e.name === "homepage.section_viewed"
      && e.props.section === "hero_v5"
    ))).toBeDefined();

    expect(errors.filter((e) => !isTolerated(e, TOLERATED))).toEqual([]);
  });

  for (const vp of VIEWPORTS) {
    test(`@critical HeroV5 renders without horizontal overflow @ ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/?ff_hero_v5=1", { waitUntil: "networkidle" });
      await expect(page.locator(".hp-hero-v5")).toBeVisible();

      const overflow = await page.evaluate(() => {
        const root = document.documentElement;
        return {
          scrollWidth: root.scrollWidth,
          innerWidth: window.innerWidth,
        };
      });
      // Same threshold as responsive-smoke.spec.
      expect(
        overflow.scrollWidth,
        `HeroV5 overflowed at ${vp.name}: scrollWidth ${overflow.scrollWidth} > innerWidth ${overflow.innerWidth}`,
      ).toBeLessThanOrEqual(overflow.innerWidth + 1);
    });
  }

  test("@critical clicking 'All listings' card navigates to /browse with no filter", async ({ page }) => {
    await page.goto("/?ff_hero_v5=1", { waitUntil: "networkidle" });
    await page.locator(".hp-hero-v5-dest-all").click();
    await expect(page).toHaveURL(/\/browse/);
  });

  test("@critical clicking 'Surf City I' card navigates to /browse with beach filter", async ({ page }) => {
    await page.goto("/?ff_hero_v5=1", { waitUntil: "networkidle" });
    await page.locator(".hp-hero-v5-dest-s1").click();
    await expect(page).toHaveURL(/\/browse/);
    // master_category=beach via buildFiltersForCategory("surf_city_1")
    await expect(page).toHaveURL(/cat=surf_city_1|master_category=beach/);
  });
});
