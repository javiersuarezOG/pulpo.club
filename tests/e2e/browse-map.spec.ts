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
import { seedConsent, seedProUser } from "./_helpers";

async function topElementAtCenter(page, selector: string) {
  return page.locator(selector).evaluate((el) => {
    const rect = el.getBoundingClientRect();
    const x = Math.round(rect.left + rect.width / 2);
    const y = Math.round(rect.top + rect.height / 2);
    const top = document.elementFromPoint(x, y);
    return {
      tag: top?.tagName ?? "",
      className: String(top?.className ?? ""),
      inDetail: !!top?.closest(".detail-overlay"),
      inDrawer: !!top?.closest(".filter-drawer-backdrop"),
      inModal: !!top?.closest(".modal-backdrop"),
      inConsent: !!top?.closest(".consent-banner"),
      inSheet: !!top?.closest(".map-sheet"),
    };
  });
}

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
    const clusterCount = page.locator(".pulpo-cluster__count").first();
    await expect(clusterCount).toBeVisible();
    const clusterAlignments = await page.locator(".pulpo-cluster").evaluateAll((clusters) =>
      clusters.map((clusterEl) => {
        const countEl = clusterEl.querySelector(".pulpo-cluster__count");
        const count = countEl?.getBoundingClientRect();
        const cluster = clusterEl.getBoundingClientRect();
        return {
          text: countEl?.textContent ?? "",
          dx: count ? Math.abs(count.left + count.width / 2 - (cluster.left + cluster.width / 2)) : 999,
          dy: count ? Math.abs(count.top + count.height / 2 - (cluster.top + cluster.height / 2)) : 999,
        };
      }),
    );
    expect(clusterAlignments.length, "visible cluster count").toBeGreaterThan(0);
    for (const alignment of clusterAlignments) {
      expect(alignment.dx, `cluster ${alignment.text} x-center`).toBeLessThanOrEqual(1);
      expect(alignment.dy, `cluster ${alignment.text} y-center`).toBeLessThanOrEqual(1);
    }

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

  test("mobile: bottom sheet + Filters pill (PR-10)", async ({ page }) => {
    await seedConsent(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/browse?view=map", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });

    // Desktop card panel is hidden; the bottom sheet + Filters pill show.
    await expect(page.locator(".map-split__cards")).toBeHidden();
    await expect(page.locator(".browse-search")).toBeHidden();
    const sheet = page.locator(".map-sheet");
    await expect(sheet).toBeVisible();
    expect(await sheet.locator(".map-sheet-row").count()).toBeGreaterThan(0);
    const mapBox = await page.locator(".map-view__canvas").evaluate((el) => {
      const rect = el.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom, height: rect.height, viewport: window.innerHeight };
    });
    expect(mapBox.top, "mobile map should enter first viewport immediately").toBeLessThanOrEqual(90);
    expect(mapBox.bottom, "mobile map should fill behind the sheet").toBeGreaterThanOrEqual(mapBox.viewport - 2);

    const collapsedScroll = await page.locator(".map-sheet__cards").evaluate((el) => ({
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
    }));
    expect(collapsedScroll.scrollWidth - collapsedScroll.clientWidth, "collapsed sheet should not be a giant horizontal rail").toBeLessThanOrEqual(1);

    const handleTop = await topElementAtCenter(page, ".map-sheet__handle");
    expect(handleTop.inSheet, "sheet handle should be tappable/topmost").toBe(true);

    // Sheet starts collapsed; tapping the handle expands it into a vertical scroller.
    await expect(sheet).toHaveClass(/map-sheet--collapsed/);
    await page.locator(".map-sheet__handle").click();
    await expect(sheet).toHaveClass(/map-sheet--expanded/);
    const expandedScroll = await page.locator(".map-sheet__cards").evaluate((el) => {
      el.scrollTop = 180;
      return {
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        overflowY: getComputedStyle(el).overflowY,
      };
    });
    expect(expandedScroll.scrollHeight).toBeGreaterThan(expandedScroll.clientHeight);
    expect(expandedScroll.scrollTop).toBeGreaterThan(0);
    expect(expandedScroll.overflowY).toMatch(/auto|scroll/);

    // Filters pill opens the existing filter drawer.
    await page.locator(".map-filters-pill").click();
    await page.locator(".filter-drawer").waitFor({ state: "visible", timeout: 3_000 });
    const drawerTop = await topElementAtCenter(page, ".map-view__canvas");
    expect(drawerTop.inDrawer, "filter drawer backdrop should sit above map panes").toBe(true);
  });

  test("[perf] mobile sheet virtualizes — only a windowed slice of rows is mounted", async ({ page }) => {
    await seedConsent(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/browse?view=map", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });
    const sheet = page.locator(".map-sheet");
    await expect(sheet).toBeVisible();

    // Worst case: expand into the full vertical scroller, then jump deep.
    await page.locator(".map-sheet__handle").click();
    await expect(sheet).toHaveClass(/map-sheet--expanded/);
    await page.locator(".map-sheet__cards").evaluate((el) => { el.scrollTop = Math.floor(el.scrollHeight / 2); });
    await page.waitForTimeout(120); // let the rAF-throttled window recompute

    const mounted = await page.locator(".map-sheet__cards .map-sheet-row").count();
    const imgs = await page.locator(".map-sheet__cards .map-sheet-row img").count();
    // The catalogue is ~1,400 mapped listings; pre-fix this sheet mounted ALL of
    // them (~54k DOM nodes / ~93MB heap). A windowed sheet mounts a tiny slice.
    expect(mounted, "sheet rows must be windowed, not the full catalogue").toBeLessThan(80);
    expect(mounted, "the window must still render rows").toBeGreaterThan(0);
    expect(imgs, "image count tracks the row window").toBeLessThan(80);

    // The scrollbar stays honest — spacers preserve the full content height.
    const { scrollHeight, clientHeight } = await page.locator(".map-sheet__cards").evaluate((el) => ({
      scrollHeight: el.scrollHeight, clientHeight: el.clientHeight,
    }));
    expect(scrollHeight, "spacers preserve the full scroll height").toBeGreaterThan(clientHeight * 3);
  });

  test("mobile map offset tracks the real header height (not a hardcoded 72px)", async ({ page }) => {
    await seedConsent(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/browse?view=map", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });

    const m = await page.evaluate(() => {
      const header = document.querySelector(".topnav");
      const prop = getComputedStyle(document.documentElement)
        .getPropertyValue("--map-mobile-top-offset").trim();
      const canvas = document.querySelector(".map-view__canvas");
      return {
        headerH: header ? Math.round(header.getBoundingClientRect().height) : 0,
        offset: parseFloat(prop),
        canvasTop: canvas ? Math.round(canvas.getBoundingClientRect().top) : -1,
      };
    });
    // The published offset must equal the measured header, proving it's dynamic.
    expect(m.headerH, "header should be measurable").toBeGreaterThan(0);
    expect(Math.abs(m.offset - m.headerH), "offset tracks the live header height").toBeLessThanOrEqual(1);
    // And the map canvas must sit below the header — never overlapping it.
    expect(m.canvasTop, "map canvas starts at or below the header bottom").toBeGreaterThanOrEqual(m.headerH - 1);
  });

  test("map panes stay below detail and conversion overlays", async ({ page }) => {
    await seedConsent(page);
    await seedProUser(page);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/browse?view=map", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });
    await page.locator(".map-split__cards .listing-card").first().click();
    await expect(page.locator(".detail-overlay")).toBeVisible();
    const detailTop = await topElementAtCenter(page, ".map-view__canvas");
    expect(detailTop.inDetail, "detail panel should sit above map panes").toBe(true);
  });

  test("map panes stay below anonymous upgrade modal", async ({ page }) => {
    await seedConsent(page);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/browse?view=map", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });
    await page.locator(".map-split__cards .listing-card").first().click();
    await expect(page.locator(".free-month-modal")).toBeVisible({ timeout: 5_000 });
    const modalTop = await topElementAtCenter(page, ".map-view__canvas");
    expect(modalTop.inModal, "upgrade modal backdrop should sit above map panes").toBe(true);
  });

  // ── WS4 map↔search sync (desktop — the mobile search box is hidden in
  //    map mode, so this surface is desktop-only by design). ──
  const intOf = (s: string | null) => parseInt((s ?? "").replace(/[^\d]/g, ""), 10);

  test("the list, the map, and the header always show the same count", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/browse?view=map", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });
    await page.locator(".map-split__cards .listing-card").first().waitFor({ state: "visible", timeout: 10_000 });

    const readCounts = async () => {
      const headerNum = intOf(await page.locator(".results-count .num").first().textContent());
      const cardCount = await page.locator(".map-split__cards .listing-card").count();
      const mapText = (await page.locator(".map-view__count").textContent()) ?? "";
      const m = mapText.match(/([\d,]+)\s+of\s+([\d,]+)/); // "X of Y listings mapped"
      const mapTotal = m ? intOf(m[2]) : NaN;
      return { headerNum, cardCount, mapTotal };
    };

    const before = await readCounts();
    expect(before.headerNum, "header == card count (initial)").toBe(before.cardCount);
    expect(before.mapTotal, "map 'of Y' == card count (initial)").toBe(before.cardCount);

    // Type a search — the header, the card list, and the map's "of Y" must
    // stay locked to the same number (the reported bug was that they diverged).
    await page.locator(".browse-search__input").fill("be"); // common substring → narrows but non-empty
    await page.waitForTimeout(700); // debounce (300ms) + refit settle

    const after = await readCounts();
    expect(after.cardCount, "search yields some matches").toBeGreaterThan(0);
    expect(after.headerNum, "header == card count (after search)").toBe(after.cardCount);
    expect(after.mapTotal, "map 'of Y' == card count (after search)").toBe(after.cardCount);
  });

  test("a query-driven refit clears a stale bbox and writes none of its own", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    // Cold-load with a stale viewport filter but NO query.
    await page.goto("/browse?view=map&bbox=13.0000,-90.0000,14.5000,-88.0000", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });

    // Typing a query is authoritative → it drops the stale bbox…
    await page.locator(".browse-search__input").fill("be");
    await page.waitForTimeout(700);
    await page.waitForFunction(() => !/[?&]bbox=/.test(window.location.search), { timeout: 3_000 });
    // …and the programmatic refit must NOT write a fresh ?bbox= back.
    expect(/[?&]bbox=/.test(new URL(page.url()).search)).toBe(false);
  });

  test("[regression] a deep-linked ?bbox= is preserved on entry (no query)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const bbox = "13.4000,-89.4000,13.6000,-89.2000";
    await page.goto(`/browse?view=map&bbox=${bbox}`, { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });
    await page.waitForTimeout(700); // let the entry effect run
    // Entry must NOT nuke the shared viewport (PR-9 shareable-bbox link).
    expect(new URL(page.url()).searchParams.get("bbox"), "inbound bbox survives entry").toBe(bbox);
  });

  test("empty-in-view panel offers a way back to all results", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    // bbox out in the Pacific — matches nothing, but the search itself has
    // matches → the "no results in this view" escape hatch, not EmptyResults.
    await page.goto("/browse?view=map&bbox=12.0000,-92.5000,12.4000,-92.0000", { waitUntil: "networkidle" });
    await page.locator(".leaflet-container").waitFor({ state: "visible", timeout: 10_000 });

    const panel = page.locator(".map-empty-inview");
    await expect(panel).toBeVisible({ timeout: 5_000 });
    await expect(page.locator(".map-split__cards .listing-card")).toHaveCount(0);

    // "Show all N" clears the viewport filter and brings the markers back.
    await panel.locator(".map-empty-inview__primary").click();
    await page.locator(".pulpo-cluster, .pulpo-pin").first().waitFor({ state: "visible", timeout: 10_000 });
    await expect(panel).toBeHidden();
    await page.waitForFunction(() => !/[?&]bbox=/.test(window.location.search), { timeout: 3_000 });
  });
});
