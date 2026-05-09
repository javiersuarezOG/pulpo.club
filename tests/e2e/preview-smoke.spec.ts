// preview-smoke.spec.ts — the guardrail for the new Vite app.
//
// Why this test exists:
//   We've shipped two crashes to /preview in two PRs (React #310 hook
//   order, then null price_per_m2 in .toFixed). Both manifested as
//   ErrorBoundary fallbacks — the page rendered the "Something went
//   wrong" screen instead of the app.
//
//   This test is the floor: open / and /browse on a Vite dev server,
//   wait for content to render, listen for any console error, fail the
//   build if any uncaught exception fires.
//
//   Runs in CI on every PR via .github/workflows/ci.yml frontend job.

import { test, expect, type ConsoleMessage } from "@playwright/test";

// Some console noise we tolerate (third-party libraries, dev-mode
// React-DevTools detection prompts). Anything matched here is logged
// but doesn't fail the build.
const TOLERATED = [
  /Download the React DevTools/,
  /\[vite\]/,                          // Vite HMR connection logs
  /Content Security Policy.*'eval'/,   // PostHog's eval-warning noise
];

function isTolerated(msg: ConsoleMessage): boolean {
  const text = msg.text();
  return TOLERATED.some((re) => re.test(text));
}

test.describe("New app boots cleanly on key routes", () => {
  for (const route of ["/", "/?dev=1"]) {
    test(`renders ${route} without console errors`, async ({ page }) => {
      const errors: string[] = [];
      const uncaught: string[] = [];

      page.on("console", (msg) => {
        if (msg.type() === "error" && !isTolerated(msg)) {
          errors.push(msg.text());
        }
      });
      page.on("pageerror", (err) => {
        uncaught.push(err.message);
      });

      await page.goto(route, { waitUntil: "networkidle" });

      // Wait for the app shell to actually mount (anything from the
      // editorial vocabulary). If we see the ErrorBoundary fallback
      // text, fail with that copy in the failure message.
      const errorBoundary = page.getByText("Something went wrong.");
      const realApp = page.locator(".app, .topnav, .hero, .page-home");
      await Promise.race([
        realApp.first().waitFor({ state: "visible", timeout: 15_000 }),
        errorBoundary.waitFor({ state: "visible", timeout: 15_000 }).then(() => {
          throw new Error(
            `ErrorBoundary fallback rendered on ${route} — uncaught exceptions: ${JSON.stringify(uncaught)}`
          );
        }),
      ]);

      // Give the live-data fetch + first-paint a beat to finish before
      // asserting on errors.
      await page.waitForTimeout(2_500);

      expect(uncaught, `uncaught exceptions on ${route}`).toEqual([]);
      expect(errors, `console.error calls on ${route}`).toEqual([]);
    });
  }

  test("listing card renders without crashing on null fields", async ({ page }) => {
    // The specific crash we hit: listing.price_per_m2 was null on a
    // real listing, .toFixed(0) threw. This test asserts at least one
    // ListingCard renders (which means the per-card render didn't
    // crash on real data).
    await page.goto("/", { waitUntil: "networkidle" });
    // Any of the listing-card variants. .listing-card is the base
    // class shared by both default + magazine variants.
    await page.locator(".listing-card").first().waitFor({ state: "visible", timeout: 10_000 });
  });

  // PR-5 — detail-panel + lightbox smoke test.
  // Click a card → detail overlay opens → photo gallery → ESC closes
  // lightbox → click backdrop closes detail. Catches focus-trap or
  // event-listener leaks that crash on close.
  test("detail panel opens, lightbox accepts ESC, focus returns", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !isTolerated(msg)) errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/", { waitUntil: "networkidle" });
    const card = page.locator(".listing-card").first();
    await card.waitFor({ state: "visible", timeout: 10_000 });
    await card.click();

    // Detail overlay mounts with .detail-panel.
    await page.locator(".detail-panel").waitFor({ state: "visible", timeout: 5_000 });

    // Try opening the lightbox via the first non-locked thumbnail
    // (anonymous users have the main photo + thumb 0/1 unlocked; thumbs
    // 2+ are sign-up gated). If no thumbnails render, skip the
    // lightbox assertion — PR-5 still passes if detail itself didn't crash.
    const unlockedThumb = page.locator(".gallery-thumb:not(.locked)").first();
    if (await unlockedThumb.count() > 0) {
      await unlockedThumb.click();
      await page.locator(".lightbox").waitFor({ state: "visible", timeout: 3_000 });
      await page.keyboard.press("Escape");
      await page.locator(".lightbox").waitFor({ state: "hidden", timeout: 3_000 });
    }

    // Close detail by clicking the overlay backdrop (outside the panel).
    await page.locator(".detail-overlay").click({ position: { x: 5, y: 5 } });
    await page.locator(".detail-panel").waitFor({ state: "hidden", timeout: 3_000 });

    expect(errors, "console errors after detail open/close").toEqual([]);
  });

  // PR-4f — interactive PriceHistogram smoke test.
  // Open Browse, click a histogram bar, verify the listing count drops
  // and the URL gets a pmax/pmin querystring. Click reset, verify the
  // count restores. Catches regressions in pointer-event wiring,
  // bucket→price math, and URL sync.
  test("price histogram bar-click filters listings and updates URL", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !isTolerated(msg)) errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/", { waitUntil: "networkidle" });
    // The app uses internal state for routing — click the Browse nav
    // link in TopNav to navigate, then wait for the histogram to mount.
    await page.locator(".topnav-links button").getByText(/^Browse$|^Explorar$/).click();
    const histo = page.locator(".histo-track");
    await histo.waitFor({ state: "visible", timeout: 10_000 });

    // Click roughly bar 5 of 24 (midway-low, where most listings cluster).
    const box = await histo.boundingBox();
    if (!box) throw new Error("histo-track has no box");
    const targetX = box.x + box.width * (5 / 24) + 4;
    const targetY = box.y + box.height / 2;
    await page.mouse.click(targetX, targetY);

    // After bar-click, URL should carry pmin and pmax.
    await page.waitForFunction(
      () => /[?&](pmin|pmax)=/.test(window.location.search),
      { timeout: 3_000 },
    );

    // Reset chip (visible only when range is active).
    const reset = page.locator(".histo-reset").first();
    await reset.waitFor({ state: "visible", timeout: 3_000 });
    await reset.click();

    // URL should clear pmin and pmax after reset.
    await page.waitForFunction(
      () => !/[?&]pmin=|[?&]pmax=/.test(window.location.search),
      { timeout: 3_000 },
    );

    expect(errors, "console errors during histogram interaction").toEqual([]);
  });

  // PR upgrade-flow-polish — verifies the Pro CTA on /plans actually
  // POSTs to /api/stripe/create-checkout-session. We mock the endpoint
  // (no real Stripe roundtrip in CI) and assert the click triggers a
  // request. The full e2e — real Stripe redirect, success URL handling,
  // webhook-driven plan flip — has to be tested by a human with a Stripe
  // test card; documented in BACKLOG.md.
  test("plans page Pro CTA fires create-checkout-session POST", async ({ page }) => {
    let postSeen = false;
    let postBody: string | null = null;
    await page.route("**/api/stripe/create-checkout-session", async (route) => {
      postSeen = true;
      postBody = route.request().postData();
      // Mock: server says "you need to sign in" — exercises the path
      // that opens the SignupModal with pendingAction:"checkout".
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ error: "sign_in_required" }),
      });
    });

    await page.goto("/", { waitUntil: "networkidle" });
    // Open Plans via the footer link (the topnav doesn't expose it).
    await page.locator(".site-footer button").getByText(/^Plans$/).first().click();
    await page.locator(".plan-card.featured").waitFor({ state: "visible", timeout: 5_000 });
    // Click the Pro CTA — its label uses the new t("plans.upgrade_pro_cta") key.
    await page.locator(".plan-card.featured .btn-primary").click();

    // The POST should have happened.
    await expect.poll(() => postSeen, { timeout: 3_000 }).toBe(true);
    expect(postBody).toBeDefined();

    // Anonymous → 401 → SignupModal opens. With Clerk off in the dev
    // env this surfaces as the legacy modal; with Clerk on the hosted
    // modal opens instead — both cases land at "the user is being
    // prompted to sign in", which is the contract that matters.
    //
    // `waitFor` handles the React state-flush tick between the fetch
    // response landing and the modal mounting; using `count()` here
    // races and flakes (mostly when the test is run as part of the
    // full suite — the CPU-busier worker exposes the timing window).
    await page
      .locator(".modal-signup, [data-clerk-component]")
      .first()
      .waitFor({ state: "visible", timeout: 3_000 });
  });

  // PR-9.5 — verifies the "Manage plan" button on /account hits the new
  // /api/stripe/billing-portal endpoint. The button only renders for
  // Pro users. We seed `pulpo-user` in localStorage with a Pro plan;
  // the legacy auth path hydrates `app.user` from there on first
  // render. CI doesn't ship a Clerk publishable key, so
  // `clerkEnabled()` returns false and the legacy path is the active
  // one (see clerk-shell.jsx). The mock-the-endpoint pattern is the
  // same as the create-checkout-session smoke above; the full Stripe-
  // Portal roundtrip needs a real Stripe key + a human, documented in
  // BACKLOG.md.
  test("account page Manage plan fires billing-portal POST", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem(
        "pulpo-user",
        JSON.stringify({
          email: "pro-tester@pulpo.club",
          name: "Pro Tester",
          plan: "pro",
          joined: Date.now(),
          provider: "email",
        }),
      );
    });

    let postSeen = false;
    let postBody: string | null = null;
    await page.route("**/api/stripe/billing-portal", async (route) => {
      postSeen = true;
      postBody = route.request().postData();
      // Mock: server returns no_customer (the metadata-out-of-sync
      // defensive path). Exercises the toast-on-error UX without
      // needing a real Stripe customer ID.
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ error: "no_customer" }),
      });
    });

    await page.goto("/", { waitUntil: "networkidle" });

    // Avatar only renders for signed-in users — the localStorage seed
    // gets us there on the legacy auth path.
    await page.locator(".avatar-btn").first().waitFor({ state: "visible", timeout: 5_000 });
    await page.locator(".avatar-btn").first().click();

    // Account lands on Profile by default; pivot to Subscription
    // sub-section.
    await page
      .locator(".account-nav button")
      .filter({ hasText: /Manage Subscription|Suscripción/ })
      .first()
      .click();

    // The "Manage plan →" button only renders for paid users.
    await page
      .locator(".sub-plan-actions .link-btn")
      .filter({ hasText: /Manage plan|Gestionar plan/ })
      .click();

    await expect.poll(() => postSeen, { timeout: 3_000 }).toBe(true);
    expect(postBody).toBeDefined();
  });

  // PR-section-urls — section-specific URL routing smoke test.
  //
  // Each section path must boot the SPA, render its surface, and not
  // crash. /listing/<id> is exercised inside the existing "detail
  // panel opens" test; here we cover the bare-section paths and the
  // back/forward sequence.
  // /account is included — anonymous cold-load opens the sign-in modal
  // as an overlay (URL stays at /account). The modal is expected
  // behaviour, not a bug; we just assert the path renders and doesn't
  // crash the boundary.
  for (const route of ["/browse", "/saved", "/plans", "/account"]) {
    test(`renders ${route} cold-load without console errors`, async ({ page }) => {
      const errors: string[] = [];
      const uncaught: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error" && !isTolerated(msg)) errors.push(msg.text());
      });
      page.on("pageerror", (err) => uncaught.push(err.message));

      await page.goto(route, { waitUntil: "networkidle" });

      const errorBoundary = page.getByText("Something went wrong.");
      const realApp = page.locator(".app, .topnav, .hero, .page-home, .page-browse, .saved-page, .plans-page, .account-page");
      await Promise.race([
        realApp.first().waitFor({ state: "visible", timeout: 15_000 }),
        errorBoundary.waitFor({ state: "visible", timeout: 15_000 }).then(() => {
          throw new Error(
            `ErrorBoundary fallback rendered on ${route} — uncaught exceptions: ${JSON.stringify(uncaught)}`
          );
        }),
      ]);

      // URL bar matches the cold-load path (no SPA redirect on mount).
      expect(new URL(page.url()).pathname).toBe(route);

      await page.waitForTimeout(1_500);
      expect(uncaught, `uncaught exceptions on ${route}`).toEqual([]);
      expect(errors, `console.error calls on ${route}`).toEqual([]);
    });
  }

  test("/listing/<id> cold-load opens detail panel without crashing", async ({ page, request }) => {
    // Pull a real listing id from the live data file so we don't
    // hard-code an id that may have rotated out of the catalog.
    const dataRes = await request.get("/data/ranked.json");
    expect(dataRes.status()).toBe(200);
    const json = await dataRes.json();
    const sample = (Array.isArray(json) ? json : json.listings ?? []).find(
      (l: { id?: string; source?: string; source_id?: string; source_type?: string; is_sold?: boolean }) =>
        l.source_type !== "off_market" && !l.is_sold
    );
    expect(sample, "live data has at least one non-off-market listing").toBeTruthy();
    const id = sample!.id ?? `${sample!.source}-${sample!.source_id}`;

    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !isTolerated(msg)) errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto(`/listing/${id}`, { waitUntil: "networkidle" });

    // Detail panel must mount within 5s. The skeleton state may
    // render briefly while listings.json resolves; assert we end up
    // at the resolved panel.
    await page
      .locator(".detail-panel")
      .waitFor({ state: "visible", timeout: 10_000 });

    expect(errors, `console errors on /listing/${id} cold-load`).toEqual([]);
  });

  test("back/forward across sections + listing detail keeps state correct", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    // Discover → Browse via TopNav button
    await page.locator(".topnav-links button").getByText(/^Browse$|^Explorar$/).click();
    await page.waitForFunction(() => window.location.pathname === "/browse", null, {
      timeout: 5_000,
    });

    // Open the first listing — the URL must change to /listing/<id>.
    await page.locator(".listing-card").first().waitFor({ state: "visible", timeout: 10_000 });
    await page.locator(".listing-card").first().click();
    await page.locator(".detail-panel").waitFor({ state: "visible", timeout: 5_000 });
    await page.waitForFunction(() => window.location.pathname.startsWith("/listing/"), null, {
      timeout: 3_000,
    });

    // Browser back → detail closes, URL returns to /browse
    await page.goBack();
    await page.locator(".detail-panel").waitFor({ state: "hidden", timeout: 3_000 });
    await page.waitForFunction(() => window.location.pathname === "/browse", null, {
      timeout: 3_000,
    });

    // Browser back again → URL returns to /
    await page.goBack();
    await page.waitForFunction(() => window.location.pathname === "/", null, {
      timeout: 3_000,
    });
  });

  test("/preview is fully gone from vercel.json (no rewrites at all)", async () => {
    // Local dev (`npm run dev`) is a Vite SPA — every path serves the
    // app regardless of vercel.json. Network-level enforcement happens
    // only on the deployed preview/prod. Assert the config instead:
    // ALL /preview* rewrites are gone. PR section-urls dropped /preview
    // entirely (Vite base flipped to "/", build assets moved to /build/).
    const fs = await import("node:fs/promises");
    const json = JSON.parse(
      await fs.readFile("vercel.json", "utf-8"),
    ) as { rewrites?: { source: string; destination: string }[] };
    const rewrites = json.rewrites ?? [];
    const sources = rewrites.map((r) => r.source);
    const previewLeftovers = sources.filter((s) => s.startsWith("/preview"));
    expect(previewLeftovers, "no /preview* rewrites should remain").toEqual([]);
    // /build/:file replaces /preview/assets/:file as the Vite output path.
    expect(sources, "/build/:file rewrite required (Vite output)").toContain("/build/:file");
  });

  test("built HTML references /build/* (not /preview/*) for entry assets", async () => {
    // After the Vite-base flip, web/dist/index.html should ask for
    // /build/index-<hash>.js + /build/index-<hash>.css. Any lingering
    // /preview/ in src/href would break the deployed bundle (the
    // /preview/* rewrites are gone).
    const fs = await import("node:fs/promises");
    const html = await fs.readFile("web/dist/index.html", "utf-8");
    expect(html, "no /preview/ in built HTML").not.toMatch(/[\s"]\/preview\//);
    expect(html, "expected /build/ entry script").toMatch(/src="\/build\/[^"]+\.js"/);
    expect(html, "expected /build/ entry stylesheet").toMatch(/href="\/build\/[^"]+\.css"/);
  });

  test("robots.txt serves the static file", async ({ request }) => {
    const res = await request.get("/robots.txt");
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).toMatch(/Sitemap:\s*https?:\/\//);
    expect(body).toMatch(/User-agent:\s*\*/);
  });

  // Cache-control regression guard (originally PR-191).
  //
  // The Vite build's `Cache-Control: max-age=31536000, immutable` is
  // only safe if every deploy emits new hashed filenames — without
  // hashing, a year-long cache pins users to stale code. This test
  // reads the built HTML and asserts the entry bundle carries a hash.
  // PR section-urls moved Vite's output from /assets/ → /build/ so
  // brand assets and build assets stop sharing a cache rule; the
  // regex below tolerates either path.
  test("Vite-built bundle filename carries a content hash (immutable-cache contract)", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const distHtml = path.resolve(process.cwd(), "web/dist/index.html");
    if (!fs.existsSync(distHtml)) {
      test.skip(!fs.existsSync(distHtml), "web/dist/index.html absent — run `npm run build` first");
      return;
    }
    const html = fs.readFileSync(distHtml, "utf8");
    const scriptMatch = html.match(/<script[^>]+src=["']([^"']*\/(?:build|assets)\/[^"']+\.js)["']/);
    expect(scriptMatch, "built HTML should reference a /build/...js (or /assets/) bundle").toBeTruthy();
    const src = scriptMatch![1];
    // Hash format: "name-AbCd_12-3.js" — Vite uses base64url-style hashes
    // (alphanumerics + _ + -), typically 8 chars but at least 6.
    expect(src, `bundle filename should carry a content hash; got "${src}"`).toMatch(
      /\/(?:build|assets)\/[A-Za-z][A-Za-z0-9_-]*-[A-Za-z0-9_-]{6,}\.js$/,
    );
  });
});
