// Share-pin landing flow. The product change: clicking /l/<token>
// (or /browse?pin=<id> directly) must drop the recipient on /browse
// with the shared listing pinned as the first card AND the detail
// panel auto-opened — NOT on the dead-end /listing/<id> page over /home
// the prior behaviour was. This spec locks in the four ways the flow
// can regress: missing rewrite, sticky pin, no panel, crash on bad id.
//
// Also asserts the existing /l/<token> token decode keeps working —
// share.ts + url-routing.ts are upstream of the new branch.

import { test, expect } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

// Base64url-encode a listing id the same way web/app/lib/share.ts does
// (btoa → +/=-stripping). Node has Buffer.toString("base64url") natively;
// using that avoids importing the browser-only share helper into a Node
// test context.
function encodeShareToken(id: string): string {
  return Buffer.from(id, "utf8").toString("base64url");
}

// Pluck a real listing id from the live /browse render so the test
// stays robust against the nightly data refresh. We read the SEO
// anchor's href (every card has <a href="/listing/<id>">).
async function firstListingIdFromBrowse(page: import("@playwright/test").Page): Promise<string> {
  await page.goto("/browse", { waitUntil: "domcontentloaded" });
  await page.locator(".listing-card .listing-card-anchor").first().waitFor({ state: "attached", timeout: 10_000 });
  const href = await page.locator(".listing-card .listing-card-anchor").first().getAttribute("href");
  expect(href).toMatch(/^\/listing\//);
  return decodeURIComponent(href!.replace(/^\/listing\//, ""));
}

test.describe("share-pin landing (desktop)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("/l/<token> on desktop pins the card at top WITHOUT auto-opening the overlay", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    const id = await firstListingIdFromBrowse(page);
    const token = encodeShareToken(id);

    await page.goto(`/l/${token}`, { waitUntil: "domcontentloaded" });

    // URL rewrite to the canonical /browse?pin=<token> form.
    await expect.poll(() => page.url(), { timeout: 5_000 }).toMatch(
      new RegExp(`\\/browse\\?(?:.*&)?pin=${token}`),
    );

    // CRITICAL: even on desktop the detail-overlay's dim+blur backdrop
    // hides the catalogue. Skip auto-open; the highlighted pinned card
    // IS the surface the recipient lands on.
    await expect(page.locator(".detail-overlay")).toBeHidden();

    // The pinned card has the highlighted class + the "Shared with you" tag.
    const firstCard = page.locator(".card-grid .listing-card").first();
    await expect(firstCard).toHaveClass(/listing-card-shared-pinned/);
    await expect(firstCard.locator("text=Shared with you")).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("user taps pinned card → panel opens → close keeps ?pin AND the tag", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    const id = await firstListingIdFromBrowse(page);

    await page.goto(`/browse?pin=${encodeURIComponent(id)}`, { waitUntil: "domcontentloaded" });
    const firstCard = page.locator(".card-grid .listing-card").first();
    await expect(firstCard).toHaveClass(/listing-card-shared-pinned/);
    await expect(page.locator(".detail-overlay")).toBeHidden();

    // Tap the pinned card → standard openListing flow pushes /listing/:id.
    await firstCard.click();
    await expect(page.locator(".detail-overlay")).toBeVisible();

    // Close the panel via "Back to results". history.back pops the
    // pushed /listing/:id entry, restoring URL to /browse?pin=<id>.
    // The pinned tag stays — closing the panel is not engagement with
    // the catalogue, so the share context is kept.
    await page.locator(".detail .link-btn").first().click();
    await expect(page.locator(".detail-overlay")).toBeHidden();
    await expect.poll(() => page.url(), { timeout: 5_000 }).toMatch(/[?&]pin=/);

    await expect(page.locator(".card-grid .listing-card").first()).toHaveClass(/listing-card-shared-pinned/);
    await expect(page.locator(".card-grid .listing-card").first().locator("text=Shared with you")).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("filter interaction clears ?pin AND the pinned-card tag (the only thing that clears it)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    const id = await firstListingIdFromBrowse(page);

    await page.goto(`/browse?pin=${encodeURIComponent(id)}`, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".card-grid .listing-card").first()).toHaveClass(/listing-card-shared-pinned/);

    // No close-the-panel step here — the panel doesn't auto-open.
    // Toggle the sort dropdown — every user-driven filter/sort path
    // funnels through clearPin(). Picking "Lowest price" guarantees a
    // real value change regardless of the current default.
    await page.locator(".sort-select").selectOption("price_asc");

    await expect.poll(() => page.url(), {
      timeout: 5_000,
      message: "Sort change should strip ?pin from URL",
    }).not.toMatch(/[?&]pin=/);
    await expect(page.locator("text=Shared with you")).toHaveCount(0);
    await expect(page.locator(".listing-card-shared-pinned")).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test("invalid pin id clears itself and renders the catalogue normally", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    await page.goto("/browse?pin=does-not-exist-anywhere", { waitUntil: "domcontentloaded" });
    // Wait for the listings hook to resolve (`browse.pin_consumed`
    // effect only fires after status="ready"). 1s is enough for the
    // local-served JSON to land.
    await page.locator(".card-grid .listing-card").first().waitFor({ state: "visible", timeout: 10_000 });

    await expect.poll(() => page.url(), {
      timeout: 5_000,
      message: "Invalid pin should be silently stripped from URL",
    }).not.toMatch(/[?&]pin=/);

    // No "Shared with you" anywhere; no panel auto-opened.
    await expect(page.locator("text=Shared with you")).toHaveCount(0);
    await expect(page.locator(".detail-overlay")).toBeHidden();

    expect(errors).toEqual([]);
  });
});

// Mobile is the critical regression surface. On a 375px viewport the
// detail-overlay is a fullscreen modal — auto-opening it on a
// share-pin landing covers 100% of the screen and hides BOTH the
// pinned card and the catalogue, defeating the entire pin feature.
// Per the PRD: on mobile, do NOT auto-navigate; the pinned card at
// the top of the grid is the invitation to tap.
test.describe("share-pin landing (mobile)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("/l/<token> on mobile pins the card at top but does NOT auto-open the overlay", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    const id = await firstListingIdFromBrowse(page);
    const token = encodeShareToken(id);

    await page.goto(`/l/${token}`, { waitUntil: "domcontentloaded" });

    // URL rewrite still happens (canonical share form).
    await expect.poll(() => page.url(), { timeout: 5_000 }).toMatch(/\/browse\?(?:.*&)?pin=/);

    // The CRITICAL mobile regression check: the fullscreen overlay must
    // NOT auto-open. The pinned card has to be the visible surface.
    await expect(page.locator(".detail-overlay")).toBeHidden();

    // The pinned card IS first in the grid with the "Shared with you" tag.
    await expect(
      page.locator(".card-grid .listing-card").first().locator("text=Shared with you"),
    ).toBeVisible();

    // Defense-in-depth: assert there's no full-viewport overlay
    // hiding the grid. Catches "I opened the overlay but hid it
    // with CSS" regressions.
    const overlayCovers = await page.evaluate(() => {
      const o = document.querySelector(".detail-overlay") as HTMLElement | null;
      if (!o) return false;
      const r = o.getBoundingClientRect();
      return r.width >= window.innerWidth * 0.9 && r.height >= window.innerHeight * 0.9;
    });
    expect(overlayCovers).toBe(false);

    expect(errors).toEqual([]);
  });
});
