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

test.describe("share-pin landing", () => {
  test("/l/<token> rewrites URL to /browse?pin and opens detail over Browse", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    const id = await firstListingIdFromBrowse(page);
    const token = encodeShareToken(id);

    await page.goto(`/l/${token}`, { waitUntil: "domcontentloaded" });

    // URL bar should rewrite away from /l/<token> to /browse?pin=<id>
    // so a refresh keeps the same surface and BrowsePage can read ?pin.
    await expect.poll(() => page.url(), {
      timeout: 5_000,
      message: "URL should rewrite from /l/<token> to /browse?pin=<id>",
    }).toMatch(/\/browse\?(?:.*&)?pin=/);

    // Detail panel auto-opens over Browse.
    await expect(page.locator(".detail-overlay")).toBeVisible();
    // The catalogue mounted underneath — the pinned card sits as the
    // first card in the grid with the "Shared with you" tag.
    await expect(
      page.locator(".card-grid .listing-card").first().locator("text=Shared with you"),
    ).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("closing the auto-opened panel drops user on /browse with pin cleared", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    const id = await firstListingIdFromBrowse(page);

    // Cold-load directly via /browse?pin= (faster than going through
    // /l/<token> — the rewrite path is covered by the test above).
    await page.goto(`/browse?pin=${encodeURIComponent(id)}`, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".detail-overlay")).toBeVisible();

    // The detail panel's "Back to results" link calls app.closeListing.
    await page.locator(".detail .link-btn").first().click();

    // URL strips ?pin entirely (replaceState, not pushState — no extra
    // history entry).
    await expect.poll(() => page.url(), {
      timeout: 5_000,
      message: "Close should drop user on /browse with ?pin gone",
    }).not.toMatch(/[?&]pin=/);

    // Panel closed; grid still rendered.
    await expect(page.locator(".detail-overlay")).toBeHidden();
    await expect(page.locator(".card-grid .listing-card").first()).toBeVisible();
    // The previously-pinned card no longer wears the "Shared with you"
    // tag — it's reverted to its natural sorted position.
    await expect(page.locator("text=Shared with you")).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test("filter interaction clears ?pin and the pinned-card tag", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    const id = await firstListingIdFromBrowse(page);

    await page.goto(`/browse?pin=${encodeURIComponent(id)}`, { waitUntil: "domcontentloaded" });
    await expect(page.locator(".card-grid .listing-card").first().locator("text=Shared with you")).toBeVisible();

    // Close the detail panel first so the filter chips are pointer-
    // reachable (the overlay covers the page underneath).
    await page.locator(".detail .link-btn").first().click();
    await expect(page.locator(".detail-overlay")).toBeHidden();

    // Toggle the sort dropdown — every user-driven filter/sort path
    // funnels through clearPin(). Picking "Lowest price" guarantees a
    // real value change regardless of the current default.
    await page.locator(".sort-select").selectOption("price_asc");

    await expect.poll(() => page.url(), {
      timeout: 5_000,
      message: "Sort change should strip ?pin from URL",
    }).not.toMatch(/[?&]pin=/);
    await expect(page.locator("text=Shared with you")).toHaveCount(0);

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
