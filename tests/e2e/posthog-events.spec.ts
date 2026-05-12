// PostHog event-catalog smoke (rewrite Phase 8).
//
// Scripted user journey across the new homepage + browse + plans
// surfaces. Asserts that the events the rewrite plan §10 inventoried
// actually fire — both the events that were already wired (kept
// firing after the rewrite) AND the events Phase 7 just added
// (browse.filter_changed, plans.viewed, shelf.config_changed +
// the Phase 4 surfaces' new events).
//
// Mechanism: the FE's track() function (web/app/telemetry/client.ts)
// pushes every call to window.__pulpoEvents__ when the URL carries
// `?posthog_capture=1`. The flag is opt-in per request and reads
// only in browsers — production traffic doesn't trigger it unless
// the URL explicitly includes the param.
//
// This avoids the realistic CI mess of:
//   - VITE_POSTHOG_KEY is unset in CI → SDK never loads
//   - Faking the key would route POSTs to the real eu.i.posthog.com
//   - Mocking posthog-js's dynamic import is gross
//
// In test mode we just inspect what the FE intended to emit.

import { test, expect } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

const URL_NEW = "/?new=1&posthog_capture=1";

type CapturedEvent = { name: string; props: Record<string, unknown>; ts: number };

async function getEvents(page: import("@playwright/test").Page): Promise<CapturedEvent[]> {
  return page.evaluate(() => {
    const w = window as unknown as { __pulpoEvents__?: CapturedEvent[] };
    return Array.isArray(w.__pulpoEvents__) ? [...w.__pulpoEvents__] : [];
  });
}

test.describe("PostHog event catalog — new homepage journey emits the expected events", () => {
  test("cold-load + navigation journey fires every wired catalog event we care about", async ({ page }) => {
    const errors = attachErrorRecorder(page);

    // ── 1. Cold-load the new homepage ────────────────────────────
    await page.goto(URL_NEW, { waitUntil: "networkidle" });

    let events = await getEvents(page);
    // landing.viewed + route.changed always fire on cold-load
    // (app.jsx mount effect). shelf.config_changed is the one-time
    // cutover marker, fires on first encounter per browser.
    expect(events.find((e) => e.name === "landing.viewed")).toBeTruthy();
    expect(events.find((e) => e.name === "route.changed")).toBeTruthy();

    // shelf.config_changed: lazy-imported, may take a tick. Poll
    // briefly so the test isn't flaky against the dynamic import
    // race. The localStorage gate persists "fired" so a re-run of
    // this spec without clearing storage skips the event — set a
    // pre-init script to wipe the gate.
    await expect.poll(async () => {
      const list = await getEvents(page);
      return list.some((e) => e.name === "shelf.config_changed");
    }, { timeout: 3_000, message: "expected shelf.config_changed to fire on first encounter" }).toBeTruthy();

    // ── 2. Click a category-grid tile → /browse with master+sub ─
    const beachTile = page.locator(
      ".category-grid-section-beach .category-grid-tile:not(:disabled)",
    ).first();
    const haveBeachTile = (await beachTile.count()) > 0;
    if (haveBeachTile) {
      await beachTile.click();
      await page.waitForURL(/\/browse/, { timeout: 5_000 });
      events = await getEvents(page);
      expect(
        events.find((e) => e.name === "category_grid.tile_clicked"),
        "category_grid.tile_clicked should fire on tile click",
      ).toBeTruthy();
      expect(
        events.find((e) => e.name === "route.changed" && e.props.to_path && String(e.props.to_path).startsWith("/browse")),
        "route.changed should fire with /browse as to_path",
      ).toBeTruthy();

      // ── 3. Toggle a filter chip on Browse → browse.filter_changed
      // The discovery-tag chip group is always present (no data dep)
      // and clicking ANY chip emits the event Phase 7 wired.
      const topRatedChip = page.locator(".filter-panel .chip", { hasText: /Top rated|Mejor valorados/ }).first();
      if (await topRatedChip.count() > 0) {
        await topRatedChip.click();
        await page.waitForTimeout(150); // chip click → state update → telemetry tick
        events = await getEvents(page);
        const filterEv = events.find((e) => e.name === "browse.filter_changed");
        expect(filterEv, "browse.filter_changed should fire on chip toggle").toBeTruthy();
        // active_count should be present and numeric (Phase 7 contract).
        expect(typeof filterEv!.props.active_count, "active_count must be a number").toBe("number");
      }
    }

    // ── 4. Navigate to /plans → plans.viewed fires on mount ──────
    await page.goto("/plans?posthog_capture=1", { waitUntil: "networkidle" });
    events = await getEvents(page);
    const plansEv = events.find((e) => e.name === "plans.viewed");
    expect(plansEv, "plans.viewed should fire on PlansPage mount").toBeTruthy();
    // source defaults to "manual" when caller didn't pass a hint.
    expect(plansEv!.props.source).toBe("manual");

    // No console errors throughout — telemetry plumbing must never
    // surface an exception.
    expect(errors).toEqual([]);
  });
});
