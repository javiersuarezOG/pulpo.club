// Shape regression for api/clerk/update-profile.js ALLOWED_PROFILE_KEYS.
//
// Why a shape test: the handler couples to Clerk's backend SDK via
// `require("../_clerk")`, which makes a true behavioral unit test
// awkward — you'd have to stub clerkClient + authenticateClerkRequest.
// The bug class we're guarding here is "someone removes country or
// language from the allowlist," which silently breaks /account/profile
// save without breaking any other call site. A regex match against the
// source is the cheapest reliable insurance.
//
// Pair with `tests/e2e/account-authed.spec.ts` for end-to-end coverage
// — that spec mutates the values via the real Clerk Backend API and
// reads them back.

import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const HANDLER = path.resolve(__dirname, "../../api/clerk/update-profile.js");

describe("api/clerk/update-profile ALLOWED_PROFILE_KEYS", () => {
  const src = fs.readFileSync(HANDLER, "utf8");

  it("includes preferred_categories (PR-B)", () => {
    expect(src).toMatch(/preferred_categories:\s*\{/);
  });

  it("includes newsletter (PR-NL filter spec)", () => {
    expect(src).toMatch(/newsletter:\s*\{[^}]*isValid:\s*isNewsletterPreference/);
  });

  it("includes country (post-2026-05-27 — /account/profile save)", () => {
    expect(src).toMatch(/country:\s*\{[\s\S]{0,200}\^\[A-Z\]\{2\}\$/);
  });

  it("includes language (post-2026-05-27 — cross-device locale)", () => {
    expect(src).toMatch(/language:\s*\{[\s\S]{0,200}NEWSLETTER_LOCALES\.has/);
  });

  it("does NOT add platform_updates yet — no backend consumer", () => {
    // Sanity check that the lie-about-persistence guardrail in
    // CLAUDE.md is being respected: writing this key would land data
    // no consumer reads, hiding a UX lie behind a real-looking API
    // call. If/when a delivery channel ships, add the field to the
    // allowlist + remove this assertion + add a consumer test.
    expect(src).not.toMatch(/platform_updates:\s*\{/);
  });
});
