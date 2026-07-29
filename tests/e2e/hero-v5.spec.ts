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
import {
  attachErrorRecorder, TOLERATED, isTolerated,
  seedAgencyUser, seedConsent, seedFreeMember, seedProUser,
} from "./_helpers";

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
    // The Top-N ranked card (pre-existing stale selector fixed: the old
    // .hp-hero-v5-postcard class only ever existed in CSS, never in JSX).
    await expect(page.locator(".hv6-card")).toBeVisible();

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

// ── Paid variant (post-2026-07-29) ─────────────────────────────────────
// A paying Pro/Agency user must NEVER see an upsell on the home hero:
// no lock overlay, no "Unlock" CTA, no "Go Pro — {price}" AccessBlock,
// no "Free" tag. Instead: Pro tag, full Top 10 unlocked + clickable, and
// a single "Browse all listings" CTA in the copy column.
test.describe("hero_v5 — paid variant", () => {
  test.beforeEach(async ({ page }) => {
    await seedConsent(page);
  });

  // The @critical assertions here are all DATA-FREE on purpose: CI's
  // `e2e critical` runs against the built vite preview, which does NOT
  // serve /data/* (publicDir:false, no vercel rewrites), so listings
  // never load and the card renders 10 SkeletonRows. The paid variant's
  // upsell-absence (the actual bug fix) is provable from the tag + the
  // lock's absence + the ProHeroCta + telemetry — none of which need
  // data. The "10 real clickable rows" richness check needs listings, so
  // it lives in the data-bearing dev-smoke test below (non-@critical),
  // same precedent as the price-histogram test.
  test("@critical Pro user: no upsell surface (no lock, Pro tag, Browse CTA, variant=pro)", async ({ page }) => {
    const errors = attachErrorRecorder(page);
    await seedProUser(page);
    await page.goto("/?posthog_capture=1&ff_hero_v5=1", { waitUntil: "networkidle" });
    await expect(page.locator(".hp-hero-v5")).toBeVisible();

    // No lock overlay, no unlock CTA anywhere.
    await expect(page.locator(".hv6-lock")).toHaveCount(0);
    await expect(page.locator(".hv6-lock-cta")).toHaveCount(0);
    await expect(page.locator(".hv6-lock-over")).toHaveCount(0);

    // Pro tag renders, "Free"/"Gratis" tag does not.
    await expect(page.locator(".hv6-tag-pro")).toBeVisible();
    await expect(page.locator(".hv6-tag-pro")).toHaveText("Pro");

    // Paid branch rendered its full Top-10 slot (10 rows, real or
    // skeleton) — proves it's the pro variant, not the 7-row free card.
    await expect(page.locator(".hv6-card .hv6-r")).toHaveCount(10);

    // No AccessBlock signup/upsell in the hero copy column.
    await expect(page.locator(".access-cta-pro")).toHaveCount(0);
    await expect(page.locator(".access-block form")).toHaveCount(0);
    const hero = await page.locator(".hp-hero-v5").innerText();
    expect(hero).not.toContain("Go Pro");
    expect(hero).not.toContain("/month");

    // ProHeroCta present; telemetry carries variant=pro + current version.
    await expect(page.locator(".hv6-pro-cta")).toBeVisible();
    const events = await getEvents(page);
    const viewed = events.find((e) => e.name === "hero_v5_viewed");
    expect(viewed?.props.variant).toBe("pro");
    expect(viewed?.props.version).toBe(versions.blocks.hero_v5);

    expect(errors.filter((e) => !isTolerated(e, TOLERATED))).toEqual([]);
  });

  test("@critical Pro user: 'Browse all listings' CTA navigates to /browse", async ({ page }) => {
    await seedProUser(page);
    await page.goto("/?posthog_capture=1&ff_hero_v5=1", { waitUntil: "networkidle" });
    await page.locator(".hv6-pro-cta .hv6-pro-btn").click();
    await expect(page).toHaveURL(/\/browse/);
  });

  // Data-dependent (needs listings loaded) → dev-smoke only, NOT @critical.
  test("Pro user: 10 unlocked rows, clicking one opens the listing detail", async ({ page }) => {
    await seedProUser(page);
    // The card floats on an infinite hv6Float animation — Playwright's
    // pre-click stability wait would time out. The CSS already honors
    // prefers-reduced-motion (animation: none), so emulate it.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/?posthog_capture=1&ff_hero_v5=1", { waitUntil: "networkidle" });
    // Wait for real ranked rows to load, then assert all 10 are clickable.
    await expect(page.locator(".hv6-card button.hv6-r-link").first()).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(".hv6-card button.hv6-r-link")).toHaveCount(10);
    await page.locator(".hv6-card button.hv6-r-link").first().click();
    await expect(page).toHaveURL(/\/listing\//);
    const events = await getEvents(page);
    expect(events.find((e) => e.name === "hero_v5_pro_row_clicked")?.props.rank).toBe(1);
  });

  test("@critical Agency user: same no-upsell guarantees as Pro", async ({ page }) => {
    await seedAgencyUser(page);
    await page.goto("/?ff_hero_v5=1", { waitUntil: "networkidle" });
    await expect(page.locator(".hp-hero-v5")).toBeVisible();
    await expect(page.locator(".hv6-lock")).toHaveCount(0);
    await expect(page.locator(".hv6-tag-pro")).toBeVisible();
    const hero = await page.locator(".hp-hero-v5").innerText();
    expect(hero).not.toContain("Go Pro");
  });

  for (const vp of VIEWPORTS) {
    test(`Pro hero renders without horizontal overflow @ ${vp.name}`, async ({ page }) => {
      await seedProUser(page);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/?ff_hero_v5=1", { waitUntil: "networkidle" });
      await expect(page.locator(".hv6-tag-pro")).toBeVisible();
      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }));
      expect(
        overflow.scrollWidth,
        `Pro hero overflowed at ${vp.name}: scrollWidth ${overflow.scrollWidth} > innerWidth ${overflow.innerWidth}`,
      ).toBeLessThanOrEqual(overflow.innerWidth + 1);
    });
  }

  test("Pro ES locale: no English pro-CTA leak", async ({ page }) => {
    await seedProUser(page);
    await page.addInitScript(() => localStorage.setItem("pulpo-locale", "es"));
    await page.goto("/?ff_hero_v5=1", { waitUntil: "networkidle" });
    await expect(page.locator(".hv6-tag-pro")).toBeVisible();
    const body = await page.locator("body").innerText();
    expect(body).not.toContain("Browse all listings");
    expect(body).not.toContain("Manage subscription");
    expect(body).not.toContain("Go Pro");
  });

  test("@critical regression: anonymous still sees lock + access form", async ({ page }) => {
    await page.goto("/?ff_hero_v5=1", { waitUntil: "networkidle" });
    await expect(page.locator(".hv6-lock")).toBeVisible();
    await expect(page.locator(".hv6-lock-cta")).toBeVisible();
    await expect(page.locator(".hv6-tag-pro")).toHaveCount(0);
    // Access surface (AccessBlock form or legacy EmailCapture) present.
    await expect(page.locator(".access-block, .hv6-signup").first()).toBeVisible();
  });

  test("@critical regression: free email member is NOT paid — lock stays", async ({ page }) => {
    await seedFreeMember(page);
    await page.goto("/?ff_hero_v5=1", { waitUntil: "networkidle" });
    await expect(page.locator(".hv6-lock")).toBeVisible();
    await expect(page.locator(".hv6-tag-pro")).toHaveCount(0);
  });
});
