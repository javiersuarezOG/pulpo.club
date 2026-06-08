// browse-map.spec.ts — WS4 PR-7 (+ extended in PR-8/9/10).
//
// The /browse map view: a third view toggle renders a Leaflet map with
// count-clusters (coords are zone-level approximations that stack, so
// clustering is on at all zooms). Asserts the toggle + ?view=map URL,
// that clusters/pins render, the honesty affordances show, and the view
// restores on reload. Tile requests may 404 in CI — markers are DOM
// overlays independent of tiles, so we assert on markers, not tiles, and
// only fail on uncaught JS exceptions.

import { test, expect } from "@playwright/test";

test.describe("Browse map view", () => {
  test("toggling to map renders clusters, the mapped-count, and ?view=map", async ({ page }) => {
    const uncaught: string[] = [];
    page.on("pageerror", (err) => uncaught.push(err.message));

    await page.goto("/browse", { waitUntil: "networkidle" });
    // Map toggle (3rd view button). EN default label.
    const mapBtn = page.locator('.view-toggle button[aria-label="Map view"]');
    await mapBtn.waitFor({ state: "visible", timeout: 10_000 });
    await mapBtn.click();

    // URL carries the shareable view param.
    await page.waitForFunction(() => /[?&]view=map/.test(window.location.search), { timeout: 3_000 });

    // Leaflet mounts + at least one cluster or pin renders.
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });
    await page.locator(".pulpo-cluster, .pulpo-pin").first().waitFor({ state: "visible", timeout: 10_000 });

    // Honesty affordances: "X of Y mapped" count + "approximate" legend.
    await expect(page.locator(".map-view__count")).toContainText(/of .* listings mapped/);
    await expect(page.locator(".map-view__legend")).toContainText("approximate");

    expect(uncaught, "uncaught JS exceptions in map view").toEqual([]);
  });

  test("clusters are size-stepped by count (PR-8)", async ({ page }) => {
    await page.goto("/browse?view=map", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });
    await page.locator(".pulpo-cluster").first().waitFor({ state: "visible", timeout: 10_000 });
    // Every cluster carries exactly one size-step modifier.
    const stepped = await page.locator(
      ".pulpo-cluster--sm, .pulpo-cluster--md, .pulpo-cluster--lg",
    ).count();
    const total = await page.locator(".pulpo-cluster").count();
    expect(stepped).toBe(total);
    expect(total).toBeGreaterThan(0);
  });

  test("?view=map cold-load restores the map directly", async ({ page }) => {
    const uncaught: string[] = [];
    page.on("pageerror", (err) => uncaught.push(err.message));

    await page.goto("/browse?view=map", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });
    await page.locator(".pulpo-cluster, .pulpo-pin").first().waitFor({ state: "visible", timeout: 10_000 });
    expect(uncaught, "uncaught JS exceptions on ?view=map cold-load").toEqual([]);
  });

  test("desktop split-pane: card panel + search-as-I-move pill (PR-9)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/browse?view=map", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });

    // Card panel renders alongside the map with cards in it.
    const panel = page.locator(".map-split__cards");
    await expect(panel).toBeVisible();
    expect(await panel.locator(".listing-card").count()).toBeGreaterThan(0);

    // "Search as I move" pill is present, ON by default, and toggles.
    const pill = page.locator(".map-view__saim");
    await expect(pill).toHaveAttribute("aria-pressed", "true");
    await pill.click();
    await expect(pill).toHaveAttribute("aria-pressed", "false");

    // Hovering a card draws the sync highlight on it.
    const firstCard = panel.locator(".listing-card").first();
    await firstCard.hover();
    await expect(firstCard).toHaveClass(/listing-card-highlighted/);
  });

  test("map view holds layout at mobile + desktop (no horizontal scroll)", async ({ page }) => {
    for (const size of [{ w: 320, h: 568 }, { w: 1280, h: 800 }]) {
      await page.setViewportSize({ width: size.w, height: size.h });
      await page.goto("/browse?view=map", { waitUntil: "networkidle" });
      await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `horizontal overflow at ${size.w}px`).toBeLessThanOrEqual(1);
    }
  });
});
