// browse-search-autocomplete.spec.ts — PR-2 (WS4).
//
// The /browse search bar gained an autocomplete dropdown: zone matches,
// land-type matches, and up to 5 title matches. This spec asserts the
// listbox renders, is keyboard-navigable, applies a structured facet on
// select, and dismisses on Escape. Runs against the Vite dev server.

import { test, expect } from "@playwright/test";
import { isTolerated } from "./_helpers";

test.describe("Browse search autocomplete", () => {
  test("renders a keyboard-navigable listbox and applies a suggestion", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !isTolerated(msg)) errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/browse", { waitUntil: "networkidle" });
    const search = page.locator(".browse-search__input");
    await search.waitFor({ state: "visible", timeout: 10_000 });

    // Type a zone-ish substring that exists in the live catalog.
    await search.fill("tunco");

    // Listbox + at least one option should appear (≥2-char gate, 150ms debounce).
    const listbox = page.locator(".browse-search__suggest[role='listbox']");
    await listbox.waitFor({ state: "visible", timeout: 3_000 });
    const options = page.locator(".browse-search__suggest-item[role='option']");
    expect(await options.count()).toBeGreaterThan(0);

    // The input advertises the open combobox.
    await expect(search).toHaveAttribute("aria-expanded", "true");

    // ArrowDown highlights the first option; Enter applies it. The first
    // suggestion is a zone (ranked by listing count) → selecting it adds
    // a zone facet, which surfaces the active-filter row and clears the
    // query.
    await search.press("ArrowDown");
    await expect(options.first()).toHaveAttribute("aria-selected", "true");
    await search.press("Enter");

    // Dropdown dismisses; a facet is now active.
    await expect(listbox).toBeHidden({ timeout: 3_000 });
    await page.locator(".active-filter-row").waitFor({ state: "visible", timeout: 3_000 });
    await expect(search).toHaveJSProperty("value", "");

    expect(errors, "console errors during autocomplete interaction").toEqual([]);
  });

  test("a no-match query shows the query-specific empty state + category pills", async ({ page }) => {
    await page.goto("/browse", { waitUntil: "networkidle" });
    const search = page.locator(".browse-search__input");
    await search.waitFor({ state: "visible", timeout: 10_000 });

    // Gibberish that matches no listing → query-specific empty state.
    await search.fill("zzzqqqxyz");
    const empty = page.locator(".empty-state");
    await empty.waitFor({ state: "visible", timeout: 5_000 });
    await expect(empty).toContainText("zzzqqqxyz");

    // At least three category-pill shortcuts.
    const pills = page.locator(".empty-pill");
    expect(await pills.count()).toBeGreaterThanOrEqual(3);

    // Clicking a pill clears the query (?q= gone) and surfaces results.
    await pills.first().click();
    await page.waitForFunction(() => !/[?&]q=/.test(window.location.search), { timeout: 3_000 });
    await expect(search).toHaveJSProperty("value", "");
    await page.locator(".listing-card").first().waitFor({ state: "visible", timeout: 5_000 });
  });

  test("Escape dismisses the dropdown before clearing the query", async ({ page }) => {
    await page.goto("/browse", { waitUntil: "networkidle" });
    const search = page.locator(".browse-search__input");
    await search.waitFor({ state: "visible", timeout: 10_000 });

    await search.fill("tunco");
    const listbox = page.locator(".browse-search__suggest[role='listbox']");
    await listbox.waitFor({ state: "visible", timeout: 3_000 });

    // First Escape closes the panel but keeps the query.
    await search.press("Escape");
    await expect(listbox).toBeHidden({ timeout: 3_000 });
    await expect(search).toHaveJSProperty("value", "tunco");

    // Second Escape clears the query.
    await search.press("Escape");
    await expect(search).toHaveJSProperty("value", "");
  });
});
