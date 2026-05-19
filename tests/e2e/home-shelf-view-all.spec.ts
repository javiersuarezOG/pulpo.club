// Home → /browse routing via shelf "View all" buttons.
//
// Two bugs we're closing the door on:
//   1. The three shelves used to pass category slugs ("price_drop",
//      "new") that didn't exist in buildFiltersForCategory's map, so
//      clicking View All landed on an unfiltered /browse. The handler
//      now passes the canonical slugs ("price_drops", "new_this_week")
//      plus a sort param for the Top 10 shelf (no filter equivalent —
//      it's just the head of the rank-sorted list).
//
//   2. Mobile-first hard rule (CLAUDE.md, post-2026-05-19): visual
//      changes have to work on mobile AND desktop. Test both viewports
//      so a future "make this fit on desktop" tweak can't silently
//      break the 375px tap target.
//
// Coverage:
//   For each viewport (375×812 mobile, 1280×800 desktop):
//     - Top 10  View All → /browse?sort=stars_desc
//     - Drops   View All → /browse?cat=price_drops&status=price_drop
//     - New     View All → /browse?cat=new_this_week&status=new
//
// The category-slug → filter mapping (status=price_drop / status=new)
// is the URL serialization that writeFilterToURL emits when the
// price_drops / new_this_week categories are applied — locked here so
// drift in either the home handler OR the filter map surfaces as a
// failed assertion rather than a silently-broken funnel.

import { test, expect, type Page } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

const VIEWPORTS = [
  { name: "375×812 mobile",   width: 375,  height: 812 },
  { name: "1280×800 desktop", width: 1280, height: 800 },
] as const;

// hero_v4 is default-on in production; force it on explicitly so the
// test is independent of the localStorage flag state on the runner.
const URL_HOME = "/?ff_hero_v4=1";

// Mobile-first tap-target floor — the button must be ≥44px on mobile
// widths. Desktop is mouse-driven so the editorial pill can be tighter
// (CSS bumps min-height back to 0 at ≥640px). The test only enforces
// 44px at mobile viewports; desktop still checks the button renders
// and that the click successfully routes.
const MIN_TOUCH_PX = 44;
const MOBILE_BREAKPOINT_PX = 640;

async function clickViewAll(page: Page, shelfId: string): Promise<void> {
  const section = page.locator(`#${shelfId}`);
  await section.waitFor({ state: "visible", timeout: 10_000 });
  const btn = section.locator(".hp-shelf-view-all");
  await btn.waitFor({ state: "visible" });
  await btn.scrollIntoViewIfNeeded();
  await btn.click();
  // Browse mounts + writeFilterToURL replaceState fires inside an
  // effect; wait for the path AND a non-empty query to settle.
  await page.waitForURL(/\/browse\?.+/, { timeout: 5_000 });
}

for (const vp of VIEWPORTS) {
  test.describe(`home shelf "View all" → /browse @ ${vp.name}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
    });

    test("Top 10 → /browse?sort=stars_desc", async ({ page }) => {
      const errors = attachErrorRecorder(page);
      await page.goto(URL_HOME, { waitUntil: "networkidle" });

      // Touch-target floor — mobile only. Desktop just confirms it
      // renders (editorial-pill desktop is intentionally tighter).
      const btn = page.locator("#hp-shelf-top10 .hp-shelf-view-all");
      await btn.waitFor({ state: "visible", timeout: 10_000 });
      const box = await btn.boundingBox();
      expect(box, "view-all bbox").not.toBeNull();
      if (vp.width < MOBILE_BREAKPOINT_PX) {
        expect(box!.height, `view-all min touch height @ ${vp.name}`).toBeGreaterThanOrEqual(MIN_TOUCH_PX);
      }

      await clickViewAll(page, "hp-shelf-top10");

      const url = new URL(page.url());
      expect(url.pathname).toBe("/browse");
      expect(url.searchParams.get("sort")).toBe("stars_desc");
      // No category leak — Top 10 is sort-only.
      expect(url.searchParams.get("cat")).toBeNull();

      expect(errors).toEqual([]);
    });

    test("Price drops → /browse?cat=price_drops with the status chip applied", async ({ page }) => {
      const errors = attachErrorRecorder(page);
      await page.goto(URL_HOME, { waitUntil: "networkidle" });
      await clickViewAll(page, "hp-shelf-drops");

      const url = new URL(page.url());
      expect(url.pathname).toBe("/browse");
      expect(url.searchParams.get("cat")).toBe("price_drops");
      // buildFiltersForCategory("price_drops") adds status=price_drop;
      // writeFilterToURL serializes that. Assert both halves so a
      // future rename of either side breaks loudly.
      expect(url.searchParams.get("status")).toBe("price_drop");

      expect(errors).toEqual([]);
    });

    test("New this week → /browse?cat=new_this_week with the status chip applied", async ({ page }) => {
      const errors = attachErrorRecorder(page);
      await page.goto(URL_HOME, { waitUntil: "networkidle" });
      await clickViewAll(page, "hp-shelf-new");

      const url = new URL(page.url());
      expect(url.pathname).toBe("/browse");
      expect(url.searchParams.get("cat")).toBe("new_this_week");
      expect(url.searchParams.get("status")).toBe("new");

      expect(errors).toEqual([]);
    });
  });
}
