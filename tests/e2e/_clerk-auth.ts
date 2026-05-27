// Helper for tests/e2e/account-authed.spec.ts.
//
// Why this exists: until now our entire e2e suite runs with Clerk OFF.
// CI never sees a signed-in user, which is exactly why two persistence
// bugs shipped to /account/profile and /account/notifications invisibly
// — there was no test that walked a real Clerk session.
//
// What it does:
//   1. Reads the five E2E_* / CLERK_* env vars from `.env.local`
//      (gitignored). Returns null if any are missing so the spec can
//      `test.skip()` cleanly in CI.
//   2. Bypasses Clerk's CAPTCHA + bot-detection in the test browser
//      via `@clerk/testing` (Clerk's official Playwright helper),
//      then signs in the test user with their password.
//   3. Snapshots the user's identity + metadata before mutations, and
//      restores it after — so the spec is idempotent across re-runs
//      and Sebas's actual production account doesn't drift.
//
// The user/password combo lives in `.env.local` only. NEVER paste them
// into a committed file or a PR body.

import type { BrowserContext, Page } from "@playwright/test";

export type AuthedTestEnv = {
  email: string;
  password: string;
  publishableKey: string;
  secretKey: string;
  baseURL: string;
};

export function readAuthedEnv(): AuthedTestEnv | null {
  const email = process.env.E2E_CLERK_USER_EMAIL;
  const password = process.env.E2E_CLERK_USER_PASSWORD;
  const publishableKey = process.env.CLERK_PUBLISHABLE_KEY || process.env.VITE_CLERK_PUBLISHABLE_KEY;
  const secretKey = process.env.CLERK_SECRET_KEY;
  const baseURL = process.env.E2E_BASE_URL || "http://localhost:5173";
  if (!email || !password || !publishableKey || !secretKey) return null;
  return { email, password, publishableKey, secretKey, baseURL };
}

// Installs Clerk's testing token on the browser context so subsequent
// page loads bypass CAPTCHA + rate-limit walls. Must run BEFORE the
// first page navigation in the test.
//
// The dynamic import keeps `@clerk/testing` out of the default e2e:smoke
// load path — if a dev forgot `npm install` after pulling the new
// devDep, only the authed spec breaks.
export async function setupClerkTesting(context: BrowserContext, env: AuthedTestEnv) {
  const { setupClerkTestingToken } = await import("@clerk/testing/playwright");
  await setupClerkTestingToken({ context, options: { publishableKey: env.publishableKey } });
}

// Drives Clerk's hosted SignIn modal through the password strategy.
// We could use Clerk's signIn API directly from Node, but driving the
// UI exercises the same path real users take — including any custom
// Pulpo behaviour layered on top of Clerk (e.g. /start redirects).
export async function signInWithPassword(page: Page, env: AuthedTestEnv): Promise<void> {
  await page.goto("/");
  // Open the sign-in modal. The header CTA is the most stable entry —
  // /start would also work, but we want the same path an existing user
  // takes.
  await page.getByRole("button", { name: /Sign in|Iniciar sesi[oó]n/i }).first().click();
  // Clerk's hosted modal renders its own DOM under `.cl-signIn-root`.
  // Wait for the email input — `setupClerkTestingToken` should already
  // have neutralised CAPTCHA so the form is interactive immediately.
  const emailInput = page.locator('input[name="identifier"], input[type="email"]').first();
  await emailInput.waitFor({ state: "visible" });
  await emailInput.fill(env.email);
  await page.getByRole("button", { name: /Continue|Continuar/i }).first().click();
  const pwInput = page.locator('input[name="password"], input[type="password"]').first();
  await pwInput.waitFor({ state: "visible" });
  await pwInput.fill(env.password);
  await page.getByRole("button", { name: /Continue|Sign in|Continuar|Iniciar/i }).first().click();
  // Wait for Clerk to settle — the modal closes once the session is
  // active. Use a DOM signal rather than `networkidle` (which flakes
  // locally per the playwright-networkidle memory).
  await page.waitForFunction(() => !document.querySelector(".cl-signIn-root, .cl-modalContent"), null, { timeout: 15_000 });
}

// Snapshot for restore-on-teardown. Reads via Clerk's Backend SDK so
// we capture the authoritative server-side state, not whatever the
// frontend currently has cached.
export type IdentitySnapshot = {
  userId: string;
  firstName: string | null;
  lastName: string | null;
  publicMetadata: Record<string, unknown>;
  hasImage: boolean;
};

async function clerkBackend(env: AuthedTestEnv) {
  // Dynamic import — same rationale as @clerk/testing above.
  const { createClerkClient } = await import("@clerk/backend");
  return createClerkClient({ secretKey: env.secretKey, publishableKey: env.publishableKey });
}

export async function snapshotUser(env: AuthedTestEnv): Promise<IdentitySnapshot> {
  const clerk = await clerkBackend(env);
  const list = await clerk.users.getUserList({ emailAddress: [env.email], limit: 1 });
  const user = Array.isArray(list.data) ? list.data[0] : list[0];
  if (!user) throw new Error(`No Clerk user for ${env.email}`);
  return {
    userId: user.id,
    firstName: user.firstName,
    lastName: user.lastName,
    publicMetadata: (user.publicMetadata as Record<string, unknown>) || {},
    hasImage: !!user.hasImage,
  };
}

export async function restoreUser(env: AuthedTestEnv, snap: IdentitySnapshot): Promise<void> {
  const clerk = await clerkBackend(env);
  // Restore identity + metadata.
  await clerk.users.updateUser(snap.userId, {
    firstName: snap.firstName ?? "",
    lastName: snap.lastName ?? "",
  });
  await clerk.users.updateUserMetadata(snap.userId, {
    publicMetadata: snap.publicMetadata,
  });
  // If we uploaded a profile image during the test, clear it. We
  // can't trivially restore the prior image (Clerk doesn't expose a
  // re-upload endpoint that takes a URL), but the test starts from
  // "no custom image" for a fresh test account so clearing is the
  // correct end state.
  if (!snap.hasImage) {
    try {
      await clerk.users.deleteUserProfileImage(snap.userId);
    } catch { /* ignore — placeholder already */ }
  }
}

// Reads back a user fresh from the Clerk backend — used between
// mutations + reloads inside the spec so we can assert the value
// genuinely round-tripped to Clerk, not just to our React state.
export async function readUser(env: AuthedTestEnv, userId: string) {
  const clerk = await clerkBackend(env);
  return clerk.users.getUser(userId);
}

// Attaches a CSP-violation listener that fails the test on any
// violation. CLAUDE.md has shipped CSP regressions twice; this is the
// guardrail that catches them on the authed path.
export function attachCspGuard(page: Page) {
  page.on("console", (msg) => {
    const text = msg.text();
    if (text.includes("Content Security Policy") || text.includes("Refused to load")) {
      throw new Error(`CSP violation during test: ${text}`);
    }
  });
}
