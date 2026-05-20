// Shared test helpers — used by all tests/e2e/*.spec.ts files.
// Single source of truth so we don't keep adding new patterns to every
// spec file (today: TOLERATED appears verbatim in three places).

import type { ConsoleMessage, Page } from "@playwright/test";

// Console noise we tolerate (third-party libraries, dev-mode React-DevTools
// detection prompts). Anything matched here is logged but doesn't fail the
// build. Keep this list curated — every entry is a known-good signal that
// would otherwise be mistaken for a regression.
export const TOLERATED: RegExp[] = [
  /Download the React DevTools/,
  /\[vite\]/,                          // Vite HMR connection logs
  /Content Security Policy.*'eval'/,   // PostHog's eval-warning noise
];

export function isTolerated(msg: ConsoleMessage): boolean {
  return TOLERATED.some((re) => re.test(msg.text()));
}

// Wire up console + pageerror listeners that stash everything the test
// assertion will care about into the returned array. The caller pushes
// the array into an `expect(errors).toEqual([])` at the end. One pattern,
// every spec.
export function attachErrorRecorder(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isTolerated(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

// localStorage seed for the legacy auth path (Clerk-off CI runs). Must
// run via addInitScript BEFORE the first navigation — sets the
// `pulpo-user` blob the legacy auth code hydrates from on first render.
// The plan field controls Pro vs Free behaviour everywhere it matters
// (account.subscription, account.notifications, paywalls).
export async function seedUser(
  page: Page,
  plan: "pro" | "free",
): Promise<void> {
  await page.addInitScript((p) => {
    localStorage.setItem(
      "pulpo-user",
      JSON.stringify({
        email: p === "pro" ? "pro-tester@pulpo.club" : "free-tester@pulpo.club",
        name: p === "pro" ? "Pro Tester" : "Free Tester",
        plan: p,
        joined: Date.now(),
        provider: "email",
      }),
    );
  }, plan);
}

// Convenience for the existing Pro-user smoke test path.
export async function seedProUser(page: Page): Promise<void> {
  await seedUser(page, "pro");
}

// Seeds a localStorage user with plan="free" but email matching the
// VITE_FOUNDER_EMAILS allowlist set in playwright.config.ts. Used to
// assert that the founder-override path (web/app/lib/founder-emails.ts)
// promotes the user to Pro on hydration so all downstream gates honor
// Pro state even though the underlying plan is free.
export async function seedFounderUser(page: Page): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem(
      "pulpo-user",
      JSON.stringify({
        email: "founder-tester@pulpo.club",
        name: "Founder Tester",
        plan: "free",
        joined: Date.now(),
        provider: "email",
      }),
    );
  });
}

// Pro user whose latest invoice failed — anchors the 14-day grace
// window at `failedDaysAgo` days before now. Used by the grace-banner
// e2e to assert the past_due UX surfaces without needing a real Stripe
// webhook event to fire.
export async function seedPastDueUser(
  page: Page,
  opts: { failedDaysAgo: number } = { failedDaysAgo: 3 },
): Promise<void> {
  await page.addInitScript((arg) => {
    const DAY = 24 * 60 * 60 * 1000;
    const GRACE_MS = 14 * DAY;
    const failedAt = Date.now() - arg.failedDaysAgo * DAY;
    localStorage.setItem(
      "pulpo-user",
      JSON.stringify({
        email: "past-due-tester@pulpo.club",
        name: "Past Due Tester",
        plan: "pro",
        subscription_status: "past_due",
        payment_failed_at: failedAt,
        grace_period_ends_at: failedAt + GRACE_MS,
        joined: Date.now(),
        provider: "email",
      }),
    );
  }, opts);
}
