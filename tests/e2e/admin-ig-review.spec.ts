// admin-ig-review.spec.ts — guardrail for the IG batch review widget.
//
// Covers two response shapes the /api/admin/ig-queue endpoint can
// produce, both rendered without console errors and without horizontal
// overflow at five viewports (CLAUDE.md mobile-first rule):
//   1. empty-state — { queue: null, hint: "..." } (no queue file yet)
//   2. loaded     — { queue: {...14 items...} }
//
// Per /admin convention the page is open (no auth check on the GET) so
// no seedUser needed.  Approval state lives in localStorage — we exercise
// the toggle to make sure the writes don't crash the widget.

import { test, expect } from "@playwright/test";
import { attachErrorRecorder } from "./_helpers";

const VIEWPORTS = [
  { name: "320×568",  width: 320,  height: 568  },   // smallest target
  { name: "375×812",  width: 375,  height: 812  },   // iPhone X-ish
  { name: "414×896",  width: 414,  height: 896  },   // iPhone Plus
  { name: "768×1024", width: 768,  height: 1024 },   // iPad portrait
  { name: "1280×800", width: 1280, height: 800  },   // desktop
] as const;

const SAMPLE_QUEUE = {
  queue: {
    version:     1,
    batch:       "drop_01",
    computed_at: "2026-05-26T12:00:00+00:00",
    config:      { plan_length: 14, llm_used: false },
    stats: {
      candidates_seen:           77,
      items_built:               14,
      items_pending_review:      12,
      items_needing_human:       1,
      items_with_lint_violations: 1,
      shelves_used: { intro: 1, top_rank_1: 1, bargain_1: 1 },
    },
    items: [
      {
        day: 1, shelf: "intro", poster_type: "typo_max", palette: "cream",
        scheduled_for: "2026-06-02T01:00:00+00:00",
        primary_listing_id: "bienesraices__test_001",
        listing_ids: ["bienesraices__test_001", "bienesraices__test_002"],
        caption: "**Test intro caption.**\n\npulpo.club",
        caption_status: "ok", lint_violations: [],
        poster_path: "web/data/ig_assets/drop_01/d01__intro/poster_typo_max_cream.png",
        carousel_photo_paths: [],
        status: "pending", approved: false,
        posted: false, posted_at: null, posted_media_id: null,
      },
      {
        day: 3, shelf: "bargain_1", poster_type: "post_it", palette: "paper",
        scheduled_for: "2026-06-04T01:00:00+00:00",
        primary_listing_id: "bienesraices__test_049",
        listing_ids: ["bienesraices__test_049"],
        caption: "**El tentáculo de Oriente trajo esto del fondo del mapa.**\n\npulpo.club · 049",
        caption_status: "lint_failed",
        lint_violations: [{ code: "BANNED_WORD", matched: "premium", span: [4, 11] }],
        poster_path: "web/data/ig_assets/drop_01/d03__bargain_1/poster_post_it_paper.png",
        carousel_photo_paths: [],
        status: "needs_human", approved: false,
        posted: false, posted_at: null, posted_media_id: null,
      },
    ],
  },
};

const EMPTY_QUEUE = {
  queue: null,
  hint: "ig_queue.json not found in web/data/. Run the builder.",
};

async function mockQueue(page: import("@playwright/test").Page, body: unknown) {
  await page.route("**/api/admin/ig-queue", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
}

async function assertNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    return {
      scrollWidth: root.scrollWidth,
      innerWidth:  window.innerWidth,
    };
  });
  // ±1px tolerance for sub-pixel rounding (matches responsive-smoke).
  expect(
    overflow.scrollWidth,
    `horizontal overflow at ${overflow.innerWidth}px (scrollWidth ${overflow.scrollWidth})`,
  ).toBeLessThanOrEqual(overflow.innerWidth + 1);
}

test.describe("/admin/ig-review", () => {
  for (const vp of VIEWPORTS) {
    test(`empty state · ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await mockQueue(page, EMPTY_QUEUE);
      const errors = attachErrorRecorder(page);

      await page.goto("/admin/ig-review", { waitUntil: "networkidle" });

      // Title set by AdminShell.
      await expect(page).toHaveTitle(/IG batch review/i);

      // Empty-state heading visible + the helpful CLI hint.
      await expect(page.getByText(/no queue yet|sin cola todavía/i)).toBeVisible();
      await expect(page.getByText(/ig_queue_builder/)).toBeVisible();

      await assertNoHorizontalOverflow(page);
      expect(errors).toEqual([]);
    });

    test(`loaded state · ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await mockQueue(page, SAMPLE_QUEUE);
      const errors = attachErrorRecorder(page);

      await page.goto("/admin/ig-review", { waitUntil: "networkidle" });

      // Stats bar shows the total count.
      await expect(page.getByText(/total/i).first()).toBeVisible();

      // Both fixture items render.
      await expect(page.getByText("D01")).toBeVisible();
      await expect(page.getByText("D03")).toBeVisible();

      // The needs_human item shows the violation alert.
      await expect(page.getByText(/BANNED_WORD/)).toBeVisible();

      // The Approve button is reachable + togglable (writes localStorage).
      const approve = page.getByRole("button", { name: /^Approve$|^Aprobar$/i }).first();
      await approve.click();
      // Once approved, the local-storage decision should be set.
      const stored = await page.evaluate(
        (key) => window.localStorage.getItem(key),
        "pulpo-ig-review-decisions/drop_01",
      );
      expect(stored || "").toContain("approve");

      await assertNoHorizontalOverflow(page);
      expect(errors).toEqual([]);
    });
  }
});
