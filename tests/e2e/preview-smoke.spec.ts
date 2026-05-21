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

import { test, expect } from "@playwright/test";
import { isTolerated, seedProUser } from "./_helpers";

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
      const realApp = page.locator(".app, .topnav, .homepage-v2, .new-homepage, .new-hero");
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
    // crash on real data). The homepage v2 redesign moved real
    // listings off /; ListingCard now mounts on /browse, so check
    // there.
    await page.goto("/browse", { waitUntil: "networkidle" });
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

    // Post-#262: anon + free clicks on a listing-card route through the
    // FreeMonthModal (matrix `shelf_card` branch). Seed a pro user so
    // the click passes through to openListing → detail panel renders.
    await seedProUser(page);

    // Homepage v2 redesign: ListingCard moved to /browse. Boot the
    // detail-panel test there.
    await page.goto("/browse", { waitUntil: "networkidle" });
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

    // Homepage v2 hides the shared TopNav on /, so navigating to
    // /browse via topnav-links from / isn't possible. Cold-load
    // /browse directly — the test's intent is the histogram itself.
    await page.goto("/browse", { waitUntil: "networkidle" });
    const histo = page.locator(".histo-track");
    await histo.waitFor({ state: "visible", timeout: 10_000 });
    // Scroll the histogram into view before clicking — Playwright's
    // `mouse.click(x, y)` uses absolute viewport coords without
    // auto-scrolling. The filter panel's vertical layout can shift
    // (e.g. adding new chip groups above) pushing the histogram
    // below the viewport, which makes the click land on nothing.
    // scrollIntoViewIfNeeded makes the bar-click coords reliable
    // regardless of panel layout.
    await histo.scrollIntoViewIfNeeded();

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

    // Homepage v2 hides the shared footer on /; navigate to /plans
    // directly. The test's intent is the Pro CTA POST, not the
    // footer-link wiring.
    await page.goto("/plans", { waitUntil: "networkidle" });
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
    await seedProUser(page);

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

    // Homepage v2 hides the shared TopNav on /, so the avatar isn't
    // visible there. Cold-load /account directly; the seeded Pro user
    // gets past the route gate and lands on Profile by default.
    await page.goto("/account", { waitUntil: "networkidle" });

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
      const realApp = page.locator(".app, .topnav, .homepage-v2, .new-homepage, .new-hero, .page-browse, .saved-page, .plans-page, .account-page");
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
    const id = sample!.id ?? `${sample!.source}__${sample!.source_id}`;

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
    // Post-#262: anon listing-card clicks open FreeMonthModal, not the
    // detail panel. Seed pro user so the matrix routes to passthrough.
    //
    // Post-PR-323: `paid_home_variant_v1` defaults to true and the
    // block registry hides `shoreline` from pro users. Force the flag
    // off via the URL override so the Pick-Your-Shoreline card is
    // still rendered — we need it to drive the / → /browse hop.
    await seedProUser(page);

    // Homepage v2 hides the shared TopNav on /. Use the Pick Your
    // Shoreline card to navigate from / → /browse, then open a
    // listing for the back/forward chain.
    await page.goto("/?ff_paid_home_variant_v1=0", { waitUntil: "networkidle" });

    // Click the Beach shoreline card to navigate to /browse.
    await page.locator(".hp-shoreline-card-beach").click();
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

  // i18n regression guard.
  //
  // We've already had two i18n bugs reach production: a `road_access`
  // key-fact rendering "Paved" in Spanish (capitalize() of the raw
  // enum), and assorted hardcoded English in aria-labels, error UIs,
  // and a "Back to results" button. The guideline (see CLAUDE.md →
  // i18n) is: every user-visible string goes through `t()`. This test
  // is the floor that catches regressions of that rule.
  //
  // Approach: switch the SPA into Spanish via localStorage (the same
  // mechanism the locale toggle uses), wait for first paint, and
  // assert the visible text on the home + a listing detail page does
  // NOT contain any of a small canary set of English words that have
  // historically slipped through. The test errs on the side of false
  // positives — when one trips, EITHER add a `t()` lookup OR (if the
  // word is genuinely shared between EN and ES, e.g. a brand name) add
  // it to the per-test SHARED_TOKENS allowlist with a justification.
  test("Spanish locale: no English canary words leak into rendered UI", async ({ page }) => {
    // Words/phrases historically rendered in English on a Spanish-
    // locale page. Each one is something we've actually shipped and
    // had to fix; adding to this list = locking that fix in.
    const ENGLISH_CANARIES = [
      "Paved", "Gravel", "Dirt",                      // road_access_type enum (the report)
      "On beach", "Walk to beach", "Near beach",      // beachfront_tier enum
      "Back to results",                              // detail-panel back link
      "Save listing", "Remove from saved",            // heart-button aria
      "Previous photo", "Next photo",                 // photo-nav aria (read by AT but visible in dev tools)
      "We couldn't load",                             // DataFetchFailed
      "Upload photo",                                 // account profile
      // Homepage v3 (dark hero redesign) — every CTA, label, or section
      // heading visible to a cold ES visitor on /. Trips when hardcoded
      // EN strings sneak in instead of t() lookups.
      "Try a free month",                             // hero primary + header CTA
      "Curated weekly",                               // hero_v4 subhead opener
      "See this week's top 10",                       // hero secondary CTA
      "Scanning",                                     // hero pre-label "SCANNING N SOURCES"
      "Just in",                                      // hero Just In pill
      "Live now",                                     // hero LIVE NOW counter
      "Pick your shoreline", "Featured deal",         // section headings
      "Built by locals", "For subscribers only",      // USP band
      "Top 10 deals", "Price drops", "New this week", // shelf headings
      "View all",                                     // shelf "View all" links
      "Sign in",                                      // header "Sign in" link
      "How it works", "Pricing",                      // header nav
      // FreeMonthModal — would be visible on ES if a click opens it
      // before the i18n keys land. Catches a regression where the
      // modal's copy gets hardcoded EN by accident.
      "Property in El Salvador",                      // free_month_modal.headline
      "Pulpo curates properties",                     // free_month_modal.body opener
      "Weekly 10 picks",                              // free_month_modal.bullet.1
      "Direct seller links",                          // free_month_modal.bullet.3
      "Maybe later",                                  // free_month_modal.cta_dismiss
      // ListingDetail in-panel upgrade CTA (broker outbound + locked
      // thumb + locked USP row). Anon + free see this CTA on ES as
      // "Contrata Pulpo Pro — 1 mes gratis"; if EN leaks the canary
      // catches it. Renders only for non-paid tiers — the detail-panel
      // scan below runs anon so the CTA is in the body text.
      "Start Pulpo Pro",                              // detail.unlock_pro_free_month (brand+plan half)
      "first month free",                             // detail.unlock_pro_free_month (offer half)
      // Incomplete-listing quality gate (feat/incomplete-listing-quality):
      // listing cards and detail page show "Not shared" when the
      // broker hasn't shared price or size; Browse FilterPanel has a
      // "Show missing details" opt-in chip. Both must localize.
      "Not shared",                                   // value.notshared.short
      "Show missing details",                         // filter.show_incomplete
    ];

    // Tokens that legitimately exist in BOTH EN and ES copy and would
    // false-positive a naive sweep. Add with a justification comment.
    const SHARED_TOKENS = [
      // (none yet — extend as needed)
    ];
    void SHARED_TOKENS;

    await page.goto("/", { waitUntil: "networkidle" });
    // Switch locale via the same localStorage key useLocale() reads at
    // mount. Reload so the SPA bootstraps in Spanish from first paint
    // (rather than re-rendering after a runtime locale flip — we want
    // the "fresh load in ES" behaviour to match what a Spanish-locale
    // user sees).
    await page.evaluate(() => localStorage.setItem("pulpo-locale", "es"));
    await page.reload({ waitUntil: "networkidle" });
    // Homepage v2 mounts under .homepage-v2; .listing-card lives on
    // /browse, not /. Wait for the homepage root, sweep, then navigate
    // to /browse to mount the detail panel for the second sweep.
    await page.locator(".homepage-v2").first().waitFor({ state: "visible", timeout: 10_000 });
    // Allow the i18n table + locale-driven re-render to settle.
    await page.waitForTimeout(500);

    // Sniff the visible body text for any canary. We use textContent
    // (not innerText) so we don't pay layout costs; aria-labels are
    // queried separately below.
    const bodyText: string = await page.evaluate(() => document.body.textContent || "");
    for (const word of ENGLISH_CANARIES) {
      expect(
        bodyText,
        `Spanish locale leaked English text on home: "${word}". Wire the source via t() against an i18n.jsx key.`,
      ).not.toContain(word);
    }

    // Navigate to /browse and click into the first card to mount the
    // detail panel. The road_access "Paved" bug was on detail; we must
    // check it. Post-listing-funnel: anon clicks on /browse listing-cards
    // now passthrough to the detail panel (matrix `shelf_card` row is
    // passthrough for all tiers), so we don't need to seed a paid user
    // here — the panel renders for anon. That also lets the canary
    // scan exercise the in-panel upgrade CTA ("Contrata Pulpo Pro —
    // 1 mes gratis"), which renders only for non-paid tiers.

    await page.goto("/browse", { waitUntil: "networkidle" });
    await page.locator(".listing-card").first().waitFor({ state: "visible", timeout: 10_000 });
    await page.locator(".listing-card").first().click();
    await page.locator(".detail-panel").waitFor({ state: "visible", timeout: 5_000 });
    await page.waitForTimeout(500);
    const detailText: string = await page.evaluate(() => document.body.textContent || "");
    for (const word of ENGLISH_CANARIES) {
      expect(
        detailText,
        `Spanish locale leaked English text on detail: "${word}". Wire the source via t() against an i18n.jsx key.`,
      ).not.toContain(word);
    }

    // aria-label sweep — these are only visible to AT users but still
    // leak the wrong language. Spot-check the photo-nav + heart aria
    // labels that we've fixed in this PR.
    const ariaLabels: string[] = await page.evaluate(() =>
      Array.from(document.querySelectorAll("[aria-label]")).map(
        (el) => el.getAttribute("aria-label") || "",
      ),
    );
    for (const word of ["Save listing", "Remove from saved", "Previous photo", "Next photo"]) {
      const hit = ariaLabels.find((l) => l.includes(word));
      expect(hit, `aria-label still in English: "${word}" — wire via t()`).toBeUndefined();
    }
  });

  // PR-C — /start ES canary. Same guardrail as the home-page canary
  // above but for the public marketing surface. Every t()-able string
  // on /start must render in Spanish when localStorage says ES.
  test("/start in Spanish — no English canary words leak", async ({ page }) => {
    const START_CANARIES = [
      // Hero
      "Property in El Salvador",         // start.hero.h1
      "Pulpo curates properties",        // start.hero.sub
      "Cancel anytime",                  // start.hero.trust_micro / .start-card-sub
      // USPs (short variants from pro.usp.*)
      "Weekly 10 picks",                 // pro.usp.alerts.short
      "Filters + smart sorting",         // pro.usp.browse.short
      "Direct seller links",             // pro.usp.links.short
      // Join card
      "Full access",                     // start.join.paid.label
      "Get access",                      // CTA labels
      "Log in",                          // start.nav.login_link
    ];

    await page.addInitScript(() => localStorage.setItem("pulpo-locale", "es"));
    await page.goto("/start", { waitUntil: "networkidle" });
    await page.locator(".start-page").waitFor({ state: "visible", timeout: 10_000 });
    await page.waitForTimeout(400);

    const bodyText: string = await page.evaluate(() => document.body.textContent || "");
    for (const word of START_CANARIES) {
      expect(
        bodyText,
        `Spanish /start leaked English text: "${word}". Wire via t() against an i18n.jsx key.`,
      ).not.toContain(word);
    }
  });

  // PR-C — Home-page Pro upsell modal ES canary. The modal mounts when
  // the URL carries a campaign signal; assert the modal copy is Spanish.
  test("/?utm_source=test in Spanish — no English canary words in upsell modal", async ({ page }) => {
    const UPSELL_CANARIES = [
      "Get Pulpo Pro",                   // pro_upsell.eyebrow
      "Find your next property",         // pro_upsell.headline
      "Get access",                      // pro_upsell.cta_primary
      "Maybe later",                     // pro_upsell.cta_dismiss
      // Long USP variants
      "Weekly 10 picks, in your inbox",  // pro.usp.alerts.headline
      "Filter and sort by what matters", // pro.usp.browse.headline
      "Direct links to every listing",   // pro.usp.links.headline
    ];

    // Clear suppression so the modal actually mounts.
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-upsell-dismissed-at"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "es");
    });
    await page.goto("/?utm_source=test", { waitUntil: "networkidle" });
    await page.locator(".pro-upsell-modal").waitFor({ state: "visible", timeout: 10_000 });
    await page.waitForTimeout(300);

    const modalText: string = await page.evaluate(() => {
      const m = document.querySelector(".pro-upsell-modal");
      return m ? m.textContent || "" : "";
    });
    for (const word of UPSELL_CANARIES) {
      expect(
        modalText,
        `Spanish upsell modal leaked English text: "${word}". Wire via t() against an i18n.jsx key.`,
      ).not.toContain(word);
    }
  });

  // 2026-05-19 — WelcomeModal post-Stripe regression guards.
  //
  // The modal that mounts on /account?welcome=1 (the Stripe-success
  // landing) shipped with copy that promised a "magic link" the user
  // never received. The actual mechanism is a Clerk invitation (set
  // your password) — so the copy created a story break with the email
  // itself and users got stuck in a resend loop.
  //
  // Three tests, all on /account?welcome=1:
  //   1. anon (Free seed) → modal renders "invitation" copy in EN+ES,
  //      no "magic link"/"enlace mágico" anywhere
  //   2. signed-in (Pro seed) → modal renders the "you're all set"
  //      variant directly, never flashes the anon variant
  //   3. resend button present + labelled correctly in both locales
  test("welcome modal anon variant: 'invitation' copy renders in EN", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    await page.goto("/account?welcome=1", { waitUntil: "networkidle" });
    await page.locator(".welcome-modal").waitFor({ state: "visible", timeout: 10_000 });

    const modalText: string = await page.evaluate(() => {
      const m = document.querySelector(".welcome-modal");
      return m ? m.textContent || "" : "";
    });
    // Body now mentions "invitation" instead of "magic link".
    expect(modalText).toContain("invitation");
    // Resend button reads "Resend my invitation" (not "Resend the link").
    expect(modalText).toContain("Resend my invitation");
    // Bug guards: these phrases must never appear in the welcome modal
    // in any locale, ever. Each is the literal copy users saw during
    // the 2026-05-19 loop. Lock the fix in.
    expect(modalText).not.toContain("magic link");
    expect(modalText).not.toContain("Resend the link");
  });

  // 2026-05-19 regression — Sebas hit a post-Stripe flow where Clerk's
  // hosted SignIn modal opened on top of the WelcomeModal because of an
  // effect-order race: the welcome effect synchronously stripped
  // ?welcome=1 from the URL, then the route-gate effect re-read the
  // (now stripped) URL and decided /account needed auth → opened the
  // SignupModal in login mode → which (under Clerk-on) trampolined to
  // clerk.openSignIn(). Fix: welcomeModalState is now initialized
  // synchronously from URL via useState initializer so the gate effect
  // sees it on first render. This test catches the regression.
  test("welcome modal: gate-bypass prevents SignupModal flash for anonymous post-Stripe landing", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    await page.goto(
      "/account?welcome=1&session_id=cs_test_assert_no_flash",
      { waitUntil: "networkidle" },
    );

    // Welcome modal must render. If the fix worked, the SignupModal
    // (login mode, gateReason=auth_required) must NOT mount alongside
    // it. Pre-fix this test would catch the gate race because the
    // SignupModal would race the welcome modal into the DOM.
    await page.locator(".welcome-modal").waitFor({ state: "visible", timeout: 10_000 });

    // Give React a settle tick — if the gate were going to mount a
    // SignupModal, this is the window where it would happen.
    await page.waitForTimeout(500);

    // Diagnostic: dump both modal classes + URL so failure messages
    // show exactly what's in the DOM.
    const dom = await page.evaluate(() => ({
      url: window.location.href,
      welcome: document.querySelectorAll(".welcome-modal").length,
      signup: document.querySelectorAll(".modal-signup").length,
      welcomeText: (document.querySelector(".welcome-modal")?.textContent || "").slice(0, 120),
    }));
    // The legacy SignupModal renders as .modal-signup. In CI
    // (Clerk-off), the bug manifests as both .welcome-modal AND
    // .modal-signup present in the DOM. Pre-fix: the gate effect
    // re-read the URL after the welcome-effect strip → ?welcome=1
    // bypass evaporated → SignupModal opened on top of WelcomeModal.
    // The AccountPage-local gate at account.jsx:79 was an additional
    // setSignupModal call site that also needed the welcome bypass.
    expect(
      dom.signup,
      `SignupModal opened on /account?welcome=1 — the gate-bypass race is back. ` +
        `See app.jsx welcomeModalState initializer + gate effect short-circuit + ` +
        `account.jsx welcome=1 bypass on the auth-gate effect. DOM: ${JSON.stringify(dom)}`,
    ).toBe(0);
  });

  test("welcome modal anon variant: 'invitación' copy renders in ES (no English canaries)", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "es");
    });
    await page.goto("/account?welcome=1", { waitUntil: "networkidle" });
    await page.locator(".welcome-modal").waitFor({ state: "visible", timeout: 10_000 });

    const modalText: string = await page.evaluate(() => {
      const m = document.querySelector(".welcome-modal");
      return m ? m.textContent || "" : "";
    });
    // Spanish copy mentions "invitación" instead of "enlace mágico".
    expect(modalText).toContain("invitación");
    expect(modalText).toContain("Reenviar la invitación");
    // Bug guards mirroring the EN test — ES variants.
    expect(modalText).not.toContain("enlace mágico");
    expect(modalText).not.toContain("Reenviar el enlace");
    // Cross-locale canary: never let the EN copy leak into the ES modal.
    expect(modalText).not.toContain("magic link");
  });

  test("welcome modal signed-in variant: Pro seed shows 'You're all set' without anon flash", async ({ page }) => {
    // Pro seed → app.user populated immediately via the localStorage
    // seed (Clerk-off CI path). With authLoaded defaulting to true in
    // the off-Clerk case, the modal must render the signed_in variant
    // on first paint — no anon flash, no "invitation" copy.
    await seedProUser(page);
    await page.addInitScript(() => localStorage.setItem("pulpo-locale", "en"));
    await page.goto("/account?welcome=1", { waitUntil: "networkidle" });
    await page.locator(".welcome-modal").waitFor({ state: "visible", timeout: 10_000 });

    // Grab the modal text IMMEDIATELY after first visibility — the
    // 3.2s auto-dismiss timer is what catches us if a tester races
    // the assertion past the dismiss. We snapshot quickly.
    const modalText: string = await page.evaluate(() => {
      const m = document.querySelector(".welcome-modal");
      return m ? m.textContent || "" : "";
    });
    // Signed-in headline.
    expect(modalText).toContain("You're all set");
    // The anon variant's "invitation" wording must not appear here.
    // If the hydration gate breaks, this would catch the regression.
    expect(modalText).not.toContain("invitation");
    expect(modalText).not.toContain("Resend my invitation");
  });

  // 2026-05-19 PR #2 — invitation-status branched copy.
  //
  // The anon-variant WelcomeModal now GETs /api/clerk/invitation-status
  // on mount and renders copy that matches what the webhook actually
  // did. Pre-PR the modal lied uniformly with "we just sent an
  // invitation" regardless of outcome. Four tests, one per
  // discriminated status, all intercepting the endpoint so we can
  // exercise each branch without a real Stripe session.
  //
  // helper: stub /api/clerk/invitation-status to return a fixed
  // payload. The modal fetches with the session_id from the URL —
  // we don't need to verify session_id round-trips, only that the
  // copy matches the returned status.
  async function stubStatus(page: import("@playwright/test").Page, status: string, extra: Record<string, unknown> = {}) {
    await page.route("**/api/clerk/invitation-status*", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status, ...extra }),
      });
    });
  }

  test("welcome modal status: invitation_pending shows canonical 'invitation' copy", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    await stubStatus(page, "invitation_pending", { email_domain: "test.com", sent_at: new Date().toISOString(), locale: "en" });
    await page.goto("/account?welcome=1&session_id=cs_test_pending", { waitUntil: "networkidle" });
    await page.locator(".welcome-modal").waitFor({ state: "visible", timeout: 10_000 });
    // Default-branch happy path: same copy as the pre-PR-2 anon body
    // + Resend CTA visible.
    const txt: string = await page.evaluate(() => document.querySelector(".welcome-modal")?.textContent || "");
    expect(txt).toContain("invitation");
    expect(txt).toContain("Resend my invitation");
    // The status-specific copies must NOT leak into this branch.
    expect(txt).not.toContain("already have a Pulpo account");
    expect(txt).not.toContain("couldn't read your email");
  });

  test("welcome modal status: user_exists swaps to 'sign in' copy with new CTA", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    await stubStatus(page, "user_exists", { email_domain: "gmail.com" });
    await page.goto("/account?welcome=1&session_id=cs_test_user_exists", { waitUntil: "networkidle" });
    await page.locator(".welcome-modal").waitFor({ state: "visible", timeout: 10_000 });
    // Give the status fetch a moment to resolve + re-render.
    await page.waitForTimeout(500);
    const txt: string = await page.evaluate(() => document.querySelector(".welcome-modal")?.textContent || "");
    // Headline + body switch to the user_exists copy, email_domain
    // gets interpolated (this also asserts the t() var interpolation
    // path works for the new keys).
    expect(txt).toContain("You already have a Pulpo account");
    expect(txt).toContain("gmail.com");
    expect(txt).toContain("Sign in");
    // CRITICAL bug guards: the canonical anon "invitation" body and
    // Resend CTA must NOT render here. Pre-PR-2 the modal showed both
    // unconditionally and users had no recovery path.
    expect(txt).not.toContain("Resend my invitation");
    // Post-2026-05-20 short copy: "We've sent an email to set up your
    // password. Open it to activate your account." We use a stable
    // substring that won't match the user_exists / no_email branches.
    expect(txt).not.toContain("set up your password");
  });

  test("welcome modal status: no_email shows support escalation", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    await stubStatus(page, "no_email");
    await page.goto("/account?welcome=1&session_id=cs_test_no_email", { waitUntil: "networkidle" });
    await page.locator(".welcome-modal").waitFor({ state: "visible", timeout: 10_000 });
    await page.waitForTimeout(500);
    const txt: string = await page.evaluate(() => document.querySelector(".welcome-modal")?.textContent || "");
    expect(txt).toContain("couldn't read your email");
    expect(txt).toContain("hello@pulpo.club");
    expect(txt).not.toContain("Resend my invitation");
  });

  test("welcome modal status: webhook_pending shows transient 'finishing your account' copy", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    await stubStatus(page, "webhook_pending");
    await page.goto("/account?welcome=1&session_id=cs_test_webhook_pending", { waitUntil: "networkidle" });
    await page.locator(".welcome-modal").waitFor({ state: "visible", timeout: 10_000 });
    await page.waitForTimeout(500);
    const txt: string = await page.evaluate(() => document.querySelector(".welcome-modal")?.textContent || "");
    // webhook_pending shares the default-branch shape (headline +
    // inbox + resend CTA), but the body switches to the
    // 'still finishing your account setup' wording so we don't
    // promise an email that hasn't been sent yet.
    expect(txt).toContain("finishing your account setup");
    // Resend remains available — it's the user-facing escape hatch.
    expect(txt).toContain("Resend my invitation");
    // We must NOT show the canonical 'we just sent an invitation'
    // body here — the webhook hasn't fired yet so that would lie.
    // Post-2026-05-20 short copy: "We've sent an email to set up your
    // password. Open it to activate your account." We use a stable
    // substring that won't match the user_exists / no_email branches.
    expect(txt).not.toContain("set up your password");
  });

  // 2026-05-20 — Clerk activation-landing regression guards.
  //
  // PR #364/365 (call it whichever): Clerk's /v1/tickets/accept
  // redirects the user to /account?__clerk_status=sign_up&__clerk_ticket=<JWT>
  // after they click the activation email. Two effects in app.jsx
  // were racing to call clerkActions.openSignUp({}) on this URL,
  // each consuming the same single-use ticket → first call rendered
  // the password form, second hung on an already-consumed ticket
  // (infinite spinner + stacked modals). The fix:
  //   - One dedicated effect (clerkTicketHandledRef) owns the
  //     activation landing, detected by `__clerk_ticket` URL param.
  //   - The pendingSignUp effect short-circuits when hasClerkTicket
  //     is true.
  //   - welcomeModalState init suppresses on __clerk_ticket so the
  //     anon WelcomeModal can't flash on top during the boot race.
  //
  // CI runs Clerk-off so clerkActions stays null; these tests assert
  // the URL-level guards (no crash, no WelcomeModal on __clerk_ticket
  // URLs). The full openSignUp → password form behavior requires the
  // live Clerk SDK and is verified manually on Vercel preview.
  test("activation landing: /account?__clerk_ticket=… does not render WelcomeModal", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    const errors: string[] = [];
    page.on("pageerror", (err) => { errors.push(`pageerror:${err.message}`); });
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(`console:${msg.text()}`);
    });

    // Synthetic ticket — Clerk's SDK isn't loaded in CI so the param
    // never gets consumed; this exercises the URL-detection guards.
    await page.goto(
      "/account?__clerk_status=sign_up&__clerk_ticket=eyJfake.test.jwt&lang=es",
      { waitUntil: "domcontentloaded" },
    );
    await page.waitForTimeout(800);

    const dom = await page.evaluate(() => ({
      url: window.location.href,
      welcome: document.querySelectorAll(".welcome-modal").length,
      signup: document.querySelectorAll(".modal-signup").length,
    }));
    expect(dom.welcome, `WelcomeModal must not render on activation landing. DOM: ${JSON.stringify(dom)}`).toBe(0);
    expect(errors.filter((e) => !/Clerk|clerk/.test(e)), `unexpected page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("activation landing: /account?welcome=1&__clerk_ticket=… belt-and-suspenders suppresses WelcomeModal", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    // Defensive: if a future redirect ever lands us on both flags,
    // the __clerk_ticket guard in the welcomeModalState initializer
    // must still suppress the modal (Clerk owns the flow).
    await page.goto(
      "/account?welcome=1&__clerk_ticket=eyJfake.test.jwt&lang=es",
      { waitUntil: "domcontentloaded" },
    );
    await page.waitForTimeout(800);
    const welcome = await page.locator(".welcome-modal").count();
    expect(
      welcome,
      "WelcomeModal must not render when both welcome=1 AND __clerk_ticket are present.",
    ).toBe(0);
  });

  // PR #371 — the real fix for the 2026-05-20 double-modal / infinite-
  // spinner bug. PR #368 only gated WelcomeModal + the pendingSignUp
  // effect; it missed THREE independent code paths that each opened a
  // modal on /account?__clerk_ticket=…:
  //   1. app.jsx route-gate effect (evaluateGate → setSignupModal)
  //   2. account.jsx AccountPage auth-gate (app.openSignup)
  //   3. app.jsx clerkTicketHandledRef (clerk.openSignUp — the intended one)
  // Paths 1+2 both triggered SignupModal → SignupModal called
  // clerk.openSignIn (mode="login"). In production this rendered a
  // SECOND Clerk portal (`cl-cardBox` spinner) stacked beneath path 3's
  // openSignUp portal. Two modals, top one spinning forever.
  //
  // CI runs Clerk-OFF so clerk.open* are no-ops; the React-side
  // SignupModal (`.modal-signup` / LegacySignupModal) is the upstream
  // signal we CAN observe. Its absence on this URL proves paths 1+2
  // are gated. Sebas walks the Vercel-live flow to confirm path 3 is
  // also working correctly (one SignUp portal, no spinner).
  test("activation landing: no SignupModal mounts (gate suppression prevents double Clerk portal)", async ({ page }) => {
    await page.addInitScript(() => {
      try { localStorage.removeItem("pulpo-user"); } catch { /* ignore */ }
      localStorage.setItem("pulpo-locale", "en");
    });
    await page.goto(
      "/account?__clerk_status=sign_up&__clerk_ticket=eyJfake.test.jwt&lang=es",
      { waitUntil: "domcontentloaded" },
    );
    await page.waitForTimeout(1200);

    const signupModals = await page.locator(".modal-signup").count();
    expect(
      signupModals,
      "SignupModal must not mount on activation landing — its clerk.openSignIn " +
        "call stacks a second Clerk portal on top of clerk.openSignUp. The route-gate " +
        "+ AccountPage gate must short-circuit on __clerk_ticket.",
    ).toBe(0);

    // AccountPage placeholder must render so the activation modal sits
    // on something rather than a blank `return null` page.
    const placeholder = await page
      .locator(".account-welcome-preview, .account-loading")
      .count();
    expect(
      placeholder,
      "AccountPage should render a neutral placeholder on activation landings, not return null.",
    ).toBeGreaterThanOrEqual(1);
  });
});
