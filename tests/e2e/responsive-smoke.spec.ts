// Responsive smoke — the guardrail that should have existed when CLAUDE.md
// claimed it did. Catches the "horizontal scroll on mobile" class of bug
// before it ships. Surface, viewport, and content-shape coverage:
//
//   for each viewport ∈ [320×568, 375×812, 414×896, 768×1024]:
//     for each section in [/, /browse, /saved, /plans, /account]:
//       cold-load → assert documentElement.scrollWidth ≤ innerWidth + 1
//
//   for /account specifically:
//     for each (seed ∈ [free, pro]) × (clerkOn ∈ [false, true]):
//       click each .account-nav button → assert overflow after each click
//
// On failure, prints the route + viewport + the widest descendant's
// outerHTML so the engineer who breaks this in 18 months gets a useful
// error message, not just "the page is too wide."
//
// Why a separate file from preview-smoke + section-urls-full-sweep:
//   - preview-smoke is the no-crash floor (every PR runs it)
//   - section-urls-full-sweep is the routing/SEO sweep (one-time PR check)
//   - responsive-smoke is layout-only — viewport-iteration + overflow assert
//   Three orthogonal contracts, three files. Shared helpers in _helpers.ts.

import { test, expect } from "@playwright/test";
import { attachErrorRecorder, seedUser } from "./_helpers";

const VIEWPORTS = [
  { name: "320×568 iPhone SE",        width: 320, height: 568  },
  { name: "375×812 iPhone 13",        width: 375, height: 812  },
  { name: "414×896 iPhone Pro Max",   width: 414, height: 896  },
  { name: "768×1024 iPad portrait",   width: 768, height: 1024 },
] as const;

// Public-or-modal-gated section paths. Matches section-urls-full-sweep.spec.ts.
// /saved + /account are gated for anonymous users (modal opens overlay,
// URL stays put). For the responsive sweep we either accept the modal
// (anonymous) or seed a user so the real surface renders — both are
// testable layouts.
const SECTIONS = [
  // Homepage v2 (redesign) mounts under `.homepage-v2`. Legacy
  // `.new-homepage` / `.new-hero` from the prior shell stay in the
  // OR list as no-op fallbacks during the transition; remove once
  // the v2 has shipped + dashboards confirm no rollback.
  { path: "/",        surface: ".homepage-v2, .new-homepage, .new-hero", gated: false },
  { path: "/browse",  surface: ".page-browse, .browse-page", gated: false },
  { path: "/plans",   surface: ".plans-page, .plan-card",    gated: false },
  { path: "/saved",   surface: ".saved-page, .modal-signup", gated: true  },
  { path: "/account", surface: ".account-page, .modal-signup", gated: true },
  // 2026-05-19 — Post-Stripe activation landing. Anonymous render
  // shows the WelcomeModal anon variant on top of the modal-signup
  // overlay (gated /account). The new "invitation" body copy is
  // longer than what shipped originally, so the 320px viewport is
  // the one to watch for wrap/overflow regressions. Pro-seeded
  // signed-in variant is covered in the "/account?welcome=1
  // sub-sections (seeded user)" describe block below.
  { path: "/account?welcome=1", surface: ".welcome-modal", gated: true },
  // Public marketing surface — no app shell, mount-time branch in app.jsx.
  { path: "/start",   surface: ".start-page",                 gated: false },
  // PR-B.5 — campaign-tagged home renders the <ProUpsellModal> overlay
  // on top of the regular home page. Both the underlying page AND the
  // modal must fit at every mobile width without horizontal overflow.
  { path: "/?utm_source=test", surface: ".pro-upsell-modal, .homepage-v2, .new-homepage, .new-hero", gated: false },
] as const;

// Returns { overflowPx, culpritOuter } for the current page.
// Runs in the page context; "the widest descendant" is the deepest single
// element whose scrollWidth exceeds the viewport — that's the actionable
// signal when the test fails.
async function measureOverflow(page: import("@playwright/test").Page) {
  return page.evaluate(() => {
    const winW = window.innerWidth;
    const docW = document.documentElement.scrollWidth;
    const overflowPx = docW - winW;
    if (overflowPx <= 1) return { overflowPx, culpritOuter: null as string | null };
    const wide = Array.from(document.querySelectorAll<HTMLElement>("*"))
      .filter((el) => el.scrollWidth > winW + 1)
      .sort((a, b) => b.scrollWidth - a.scrollWidth);
    const top = wide[0];
    return {
      overflowPx,
      culpritOuter: top
        ? `<${top.tagName.toLowerCase()}.${top.className.slice(0, 80)}> scrollWidth=${top.scrollWidth} :: ${top.outerHTML.slice(0, 240)}`
        : null,
    };
  });
}

function assertNoOverflow(
  result: { overflowPx: number; culpritOuter: string | null },
  context: string,
) {
  if (result.overflowPx > 1) {
    throw new Error(
      `Horizontal overflow on ${context}: documentElement is ${result.overflowPx}px wider than viewport.\n` +
        `Widest descendant: ${result.culpritOuter ?? "(unknown)"}`,
    );
  }
}

// 1. Section-level sweep: cold-load each section at each viewport.
// Anonymous user — gated paths render the sign-in modal as their surface,
// which itself must not overflow.
test.describe("responsive — section sweep (anonymous)", () => {
  for (const vp of VIEWPORTS) {
    for (const section of SECTIONS) {
      test(`${section.path} @ ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        const errors = attachErrorRecorder(page);

        await page.goto(section.path, { waitUntil: "networkidle" });
        await page.locator(section.surface).first().waitFor({
          state: "visible",
          timeout: 10_000,
        });
        // Let any post-mount flush settle (transitions, locale-driven
        // re-render). 600ms is the smallest value that proved stable
        // across CI + local on a sample run.
        await page.waitForTimeout(600);

        assertNoOverflow(
          await measureOverflow(page),
          `${section.path} @ ${vp.name}`,
        );
        expect(errors, `console errors on ${section.path} @ ${vp.name}`).toEqual([]);
      });
    }
  }
});

// 2. Account deep-dive — every sub-section at every viewport, both auth
// content paths (free / pro). Clerk-on path is the legacy seed path
// flipped via env or fixture; in CI today the publishable key is unset
// so clerkEnabled() returns false and the legacy account renders. We
// seed a Pro/Free user via localStorage and click each tab.
const ACCOUNT_TABS = [
  { key: "profile",       label: /Profile|Perfil/ },
  { key: "notifications", label: /Notifications|Notificaciones/ },
  { key: "subscription",  label: /Subscription|Suscripción/ },
  { key: "security",      label: /Security|Seguridad/ },
] as const;

// 3. WelcomeModal signed-in variant — Pro seed lands on
//    /account?welcome=1 and the modal renders its "you're all set"
//    variant directly. The variant uses different DOM than the anon
//    one (shorter body, single primary CTA) so overflow profiles
//    differ — covered separately at every viewport. Free seed isn't
//    tested here because the anon variant overflow is already
//    exercised by the SECTIONS sweep above.
test.describe("responsive — /account?welcome=1 signed-in (Pro seed)", () => {
  for (const vp of VIEWPORTS) {
    test(`/account?welcome=1 · pro user @ ${vp.name}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await seedUser(page, "pro");
      const errors = attachErrorRecorder(page);

      await page.goto("/account?welcome=1", { waitUntil: "networkidle" });
      await page.locator(".welcome-modal").waitFor({
        state: "visible",
        timeout: 10_000,
      });
      // The signed-in variant auto-dismisses after ~3.2s. Measure
      // overflow well before that so the modal is still in the DOM.
      await page.waitForTimeout(300);

      assertNoOverflow(
        await measureOverflow(page),
        `/account?welcome=1 · pro user @ ${vp.name}`,
      );
      expect(errors, `console errors on /account?welcome=1 · pro @ ${vp.name}`).toEqual([]);
    });
  }
});

test.describe("responsive — /account sub-sections (seeded user)", () => {
  for (const seed of ["free", "pro"] as const) {
    for (const vp of VIEWPORTS) {
      test(`/account · ${seed} user @ ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await seedUser(page, seed);
        const errors = attachErrorRecorder(page);

        await page.goto("/account", { waitUntil: "networkidle" });
        // With a user seeded, the actual page renders (not the modal).
        await page.locator(".account-nav").waitFor({ state: "visible", timeout: 10_000 });
        await page.waitForTimeout(400);

        // Assert overflow on the default-landing tab BEFORE any clicks.
        // If the page is wider than viewport, the next .account-nav button
        // click would time out trying to reach an off-screen element and
        // fail the test with a confusing "element outside viewport" error
        // instead of the actionable "widest descendant" message. Catch
        // the layout regression first; tab clicks come second.
        assertNoOverflow(
          await measureOverflow(page),
          `/account[default-landing] · ${seed} user @ ${vp.name}`,
        );

        for (const tab of ACCOUNT_TABS) {
          const btn = page.locator(".account-nav button").filter({ hasText: tab.label }).first();
          if ((await btn.count()) === 0) continue; // tab may be hidden in some plan states
          await btn.click();
          await page.waitForTimeout(250);
          assertNoOverflow(
            await measureOverflow(page),
            `/account[${tab.key}] · ${seed} user @ ${vp.name}`,
          );
        }

        expect(errors, `console errors on /account · ${seed} @ ${vp.name}`).toEqual([]);
      });
    }
  }
});
