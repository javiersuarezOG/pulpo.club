// Discover-photo regression guardrail (added 2026-05-12).
//
// Reproduces the exact navigation path that surfaced the React +
// browser-cache opacity-stuck bug: Discover → Browse → listing detail →
// back to Discover. Cached <img>s on the second visit would load
// synchronously from cache before React attached the onLoad listener;
// setLoaded(true) never fired; opacity stayed at 0; users saw the
// skeleton over a fully decoded image and reported "photos not
// loading."
//
// The fix in web/app/components.jsx Photo (imgRef + complete-check in
// the URL-change effect) covers this. This spec is the CI gate that
// keeps it covered. It asserts every visible card photo, post-back-nav,
// has rendered pixels (naturalWidth > 0) within 8s AND no parent has
// the .photo-skeleton overlay visible.

import { test, expect } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

test.describe("Discover photos — no skeleton-stuck after navigation", () => {
  test("nav Discover → Browse → detail → back: every visible photo loads", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    // 1. Cold-load Discover.
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // 2. Browse — forces the browser to fetch + cache a different set of
    // listing photos (some overlap with Discover is the bug trigger).
    await page.goto("/browse");
    await page.waitForLoadState("networkidle");
    // Wait until at least one card photo has decoded so we know the
    // listings layer has hydrated.
    await page.waitForFunction(
      () => Array.from(document.querySelectorAll(".photo-wrap img"))
        .some((img) => (img as HTMLImageElement).naturalWidth > 0),
      null,
      { timeout: 15_000 },
    );

    // 3. Open a detail panel — exercises the detail-photo render path
    // and (importantly) keeps the cards in the browser image cache.
    //
    // Target the .listing-card ARTICLE wrapper rather than the bare
    // anchor. The anchor (.listing-card-anchor) exists for SEO +
    // middle-click but is positioned absolutely BEHIND the card-body
    // div, so Playwright's actionability check reports "<div
    // class='listing-card-body'> intercepts pointer events" and the
    // click retries until the test times out. The article wrapper is
    // the real interactive surface — onClick=handleClick is wired to
    // openListing, same path as a user tap.
    const firstCard = page.locator("article.listing-card").first();
    if (await firstCard.count()) {
      await firstCard.click();
      await page.waitForLoadState("networkidle");
      // Close the detail with browser back to keep history natural.
      await page.goBack();
      await page.waitForLoadState("networkidle");
    }

    // 4. Navigate back to Discover. This is the failure-trigger
    // transition — pre-fix, cached card photos would be stuck.
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // 5. Assert every visible card photo in viewport has rendered
    // pixels and no skeleton is sitting on top of it. Visibility is
    // checked via boundingBox so off-screen lazy-load placeholders
    // (which legitimately haven't fetched yet) don't trip the test.
    await expect.poll(
      async () => page.evaluate(() => {
        const wraps = Array.from(document.querySelectorAll(".photo-wrap"));
        const visible = wraps.filter((w) => {
          const r = (w as HTMLElement).getBoundingClientRect();
          return r.top < window.innerHeight && r.bottom > 0 && r.width > 0;
        });
        const stuck = visible.filter((w) => {
          const img = w.querySelector("img") as HTMLImageElement | null;
          const skeleton = w.querySelector(".photo-skeleton");
          // A photo is "stuck" if it has a skeleton AND either no img
          // or an img that hasn't decoded any pixels.
          const hasSkel = !!skeleton;
          const undecoded = !img || img.naturalWidth === 0;
          return hasSkel && undecoded;
        });
        return {
          visible: visible.length,
          stuck: stuck.length,
          firstStuckSrc: stuck[0]?.querySelector("img")?.getAttribute("src") || null,
        };
      }),
      {
        timeout: 10_000,
        intervals: [250, 500, 1000],
        message: "Discover card photos must finish loading within 10s after Browse-detail-back navigation",
      },
    ).toMatchObject({ stuck: 0 });

    // No console errors / pageerrors during the whole flow (the existing
    // smoke contract from _helpers.ts).
    expect(errors).toEqual([]);
  });
});
