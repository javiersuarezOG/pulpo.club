// Cross-page integrity sweep for the section-urls PR.
//
// Tests every new section path end-to-end: cold-load → URL bar matches →
// SPA mounts → no console errors → key UX (modal-on-anon, gate-on-saved)
// works. Also asserts no /preview leakage anywhere user-visible.
//
// Runs alongside preview-smoke.spec.ts. Smoke is the per-PR floor;
// this sweep is the deeper "did the routing PR introduce any
// regressions across the app surface" check.

import { test, expect, type ConsoleMessage } from "@playwright/test";

const TOLERATED = [
  /Download the React DevTools/,
  /\[vite\]/,
  /Content Security Policy.*'eval'/,
];

function isTolerated(msg: ConsoleMessage): boolean {
  return TOLERATED.some((re) => re.test(msg.text()));
}

// Convenience: collect console errors for a single page lifecycle and
// return them at the end so the test can assert on them.
function attachErrorRecorder(page: import("@playwright/test").Page) {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isTolerated(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

test.describe("Section URLs — full app sweep", () => {
  // 1. Per-section cold load: URL stays put, no console errors, the
  //    expected page surface is visible. The /saved + /account paths
  //    open the sign-in modal as an overlay (URL still stays put).
  const SECTIONS: Array<{ path: string; surface: string; modalExpected: boolean }> = [
    { path: "/",        surface: ".hero, .page-home",                 modalExpected: false },
    { path: "/browse",  surface: ".page-browse, .browse-page",        modalExpected: false },
    { path: "/saved",   surface: ".saved-page, .modal-signup",        modalExpected: true  },
    { path: "/plans",   surface: ".plans-page, .plan-card",           modalExpected: false },
    { path: "/account", surface: ".account-page, .modal-signup",      modalExpected: true  },
  ];

  for (const { path, surface, modalExpected } of SECTIONS) {
    test(`${path}: cold-load keeps URL, mounts surface, no console errors`, async ({ page }) => {
      const errors = attachErrorRecorder(page);

      await page.goto(path, { waitUntil: "networkidle" });

      // Surface must be visible within 10s.
      await page.locator(surface).first().waitFor({ state: "visible", timeout: 10_000 });

      // URL bar matches the cold-load path. The route-gate's modal does
      // NOT change the URL — that's the contract.
      expect(new URL(page.url()).pathname, `URL after cold-load on ${path}`).toBe(path);

      // No ErrorBoundary fallback.
      const eb = await page.getByText("Something went wrong.").count();
      expect(eb, `ErrorBoundary on ${path}`).toBe(0);

      // For gated paths, the sign-in modal must be visible.
      if (modalExpected) {
        const modal = page.locator(".modal-signup, [data-clerk-component]").first();
        await modal.waitFor({ state: "visible", timeout: 5_000 });
      }

      await page.waitForTimeout(1_000);
      expect(errors, `console errors on ${path}`).toEqual([]);
    });
  }

  // 2. Per-section <title> sanity. The home title is marqueed (it
  //    rotates char-by-char), so a static substring match is fragile
  //    on /. For other sections the title is stable. Assert each
  //    section's title contains a section-specific substring that
  //    survives even when the marquee wraps.
  const TITLE_NEEDLES: Record<string, RegExp> = {
    "/":        /Salvador|Beach|raw land/i,
    "/browse":  /Browse|Explorar|beachfront/i,
    "/saved":   /saved|guardad/i,
    "/plans":   /Plans|pricing|Planes/i,
    "/account": /account|cuenta/i,
  };
  test("each section sets a unique, descriptive document.title", async ({ page }) => {
    const titles: Record<string, string> = {};
    for (const { path } of SECTIONS) {
      await page.goto(path, { waitUntil: "networkidle" });
      await page.waitForTimeout(500); // let useDocumentMeta apply
      titles[path] = await page.title();
      expect(titles[path], `${path} title`).toMatch(TITLE_NEEDLES[path]);
    }
    // Non-home titles should all be distinct (no marquee mutating them).
    const uniqueNonHome = new Set(
      Object.entries(titles)
        .filter(([k]) => k !== "/")
        .map(([, v]) => v),
    );
    expect(uniqueNonHome.size, "non-home titles all distinct").toBe(SECTIONS.length - 1);
  });

  // 3. Canonical URL + hreflang sanity per section.
  test("each section emits canonical + hreflang link tags", async ({ page }) => {
    for (const { path } of SECTIONS) {
      await page.goto(path, { waitUntil: "networkidle" });
      await page.waitForTimeout(500);
      const canonical = await page
        .locator('link[rel="canonical"]')
        .getAttribute("href");
      expect(canonical, `canonical on ${path}`).toBeTruthy();
      const hrefEs = await page
        .locator('link[rel="alternate"][hreflang="es"]')
        .getAttribute("href");
      expect(hrefEs, `hreflang=es on ${path}`).toContain("lang=es");
    }
  });

  // 4. /preview is gone from the user surface. No anchor or button
  //    href should mention /preview as a navigation target. (The
  //    asset path /preview/assets/<hash>.js may still appear in
  //    <script src> — that's the build internal, not a user URL.)
  test("no user-facing link points at /preview", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    const previewLinks = await page
      .locator('a[href^="/preview"], a[href^="/preview/"]')
      .count();
    expect(previewLinks, "anchors targeting /preview").toBe(0);
    // Footer + Plans + Account should also be checked since they may
    // hard-code different paths.
    for (const { path } of SECTIONS) {
      await page.goto(path, { waitUntil: "networkidle" });
      const n = await page
        .locator('a[href^="/preview"], a[href^="/preview/"]')
        .count();
      expect(n, `/preview anchors on ${path}`).toBe(0);
    }
  });

  // 5. Listing-card hidden anchor exists + targets /listing/<id>.
  //    Crawler-visibility check: the card body must contain a real
  //    <a href> for SEO + cmd-click.
  test("listing card has a crawlable anchor pointing at /listing/<id>", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    const card = page.locator(".listing-card").first();
    await card.waitFor({ state: "visible", timeout: 10_000 });
    const anchorHref = await card.locator(".listing-card-anchor").getAttribute("href");
    expect(anchorHref, "card anchor href").toMatch(/^\/listing\/[^/?]+$/);
  });
});
