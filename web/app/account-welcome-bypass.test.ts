// Shape regression for the post-Stripe modal-loop bug.
//
// Background: in PR #314, the App-level route-gate was correctly
// changed to consult a synchronously-initialized `welcomeModalState`
// React state instead of re-reading `window.location.search` (which
// races the welcome effect that strips `?welcome=1`). But the
// AccountPage-local auth-gate at account.jsx:79-93 was "fixed" using
// the URL re-read pattern, so it still loses the race when Clerk is
// ON in production — `clerkBooting` early-returns on first mount,
// the welcome effect strips the URL, and when the effect re-fires
// post-clerk-hydration the URL no longer carries `welcome=1` → the
// bypass evaporates → SignupModal opens → Clerk's hosted SignIn modal
// trampolines on top of the WelcomeModal.
//
// A true behavioral test of this bug requires a real Clerk-ON browser
// (the race is in the clerkBooting transition that CI never reaches).
// This shape test is the practical guardrail: it reads account.jsx
// and asserts the URL re-read pattern is GONE from the post-fix
// auth-gate effect AND the matching render branch. If anyone restores
// the URL re-read shape — accidentally or via a copy-paste from old
// references — this test goes red.
//
// Pair with the e2e regression at
// `tests/e2e/preview-smoke.spec.ts` "welcome modal: gate-bypass
// prevents SignupModal flash" which covers the Clerk-OFF surface.

import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const accountSrc = fs.readFileSync(
  path.join(__dirname, "account.jsx"),
  "utf8",
);

describe("AccountPage post-Stripe welcome bypass", () => {
  it("auth-gate effect consults app.welcomeModalState (not window.location.search)", () => {
    // The effect's deps include app.welcomeModalState so that a Clerk-ON
    // boot transition (clerkBooting true→false) re-evaluates against
    // the synchronous state, not a URL that the welcome effect has
    // already stripped.
    expect(accountSrc).toMatch(/if \(app\.welcomeModalState\) return;/);
    expect(accountSrc).toMatch(/\[clerkBooting,\s*app\.user,\s*app\.welcomeModalState,\s*app\.clerkActions\]/);
  });

  it("auth-gate effect short-circuits on pending Clerk invitation sign-up", () => {
    // When Clerk has a pending sign-up (post-invitation-ticket but
    // password not set), the dedicated app.jsx effect opens
    // clerk.openSignUp({}) for password creation. The local auth-gate
    // here must not race + stack a SignupModal on top. See 2026-05-20
    // post-activation-flow bug.
    expect(accountSrc).toMatch(/app\.clerkActions[\s\S]{0,150}pendingSignUp/);
    expect(accountSrc).toMatch(/pendingSignUp\(\)\)?\) return;\s*\n\s*app\.openSignup/);
  });

  it("no URL re-read for welcome-bypass anywhere in AccountPage", () => {
    // The bug pattern. If this matches, someone has reintroduced the
    // window.location.search re-read for the welcome bypass. The fix
    // is to use app.welcomeModalState which is initialized synchronously
    // from the URL by app.jsx's useState initializer (see app.jsx:481).
    const urlReadBypass = /URLSearchParams\(window\.location\.search\)[\s\S]{0,80}welcome/;
    expect(accountSrc).not.toMatch(urlReadBypass);
  });

  it("welcome-preview render branch consults app.welcomeModalState", () => {
    // The placeholder div is what the user sees behind the WelcomeModal
    // while auth resolves. If this reverts to a URL re-read, the
    // placeholder never shows in production (Clerk-ON) because the
    // strip already ran by the time the render runs.
    expect(accountSrc).toMatch(
      /if \(app\.welcomeModalState\) \{\s*\n\s*return <div className="page page-account account-welcome-preview"/,
    );
  });
});
