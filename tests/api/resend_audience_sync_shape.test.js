// Shape regression for the Pro→Resend audience sync wiring:
//
//   api/_resend_audience.js                    — shared helper
//   api/stripe/webhook.js                      — enroll on Pro upgrade,
//                                                unsubscribe on plan loss
//   scripts/backfill_resend_audience.mjs       — one-time backfill
//
// All three pieces ship together (PR after #565). Without the sync,
// Pro users entitled in Clerk via Stripe never made it into the Resend
// audience the newsletter pipeline reads — audience-count intersection
// returned 0 on production (1 Resend ∩ 9 Clerk Pro).
//
// Behavioural coverage of the Resend HTTP calls lives in e2e tests
// (when they land); this file is the cheap reliable contract that
// catches a refactor silently dropping one of the wire-ups.

import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const HELPER = path.resolve(__dirname, "../../api/_resend_audience.js");
const WEBHOOK = path.resolve(__dirname, "../../api/stripe/webhook.js");
const BACKFILL = path.resolve(__dirname, "../../scripts/backfill_resend_audience.mjs");

const helperSrc = fs.readFileSync(HELPER, "utf8");
const webhookSrc = fs.readFileSync(WEBHOOK, "utf8");
const backfillSrc = fs.readFileSync(BACKFILL, "utf8");

describe("api/_resend_audience.js helper", () => {
  it("exports enrollPaidUserInAudience and unsubscribeOnPlanLoss", () => {
    expect(helperSrc).toMatch(/module\.exports\s*=\s*\{[\s\S]*enrollPaidUserInAudience[\s\S]*unsubscribeOnPlanLoss[\s\S]*\}/);
  });

  it("posts to the correct Resend audience endpoint", () => {
    expect(helperSrc).toMatch(/audiences\/\$\{audienceId\}\/contacts/);
    expect(helperSrc).toMatch(/method:\s*"POST"/);
  });

  it("encodes locale via the pulpo-locale first_name side-channel", () => {
    // Matches the contract documented in api/newsletter.js — keeps the
    // newsletter pipeline's locale-from-first_name parser working.
    expect(helperSrc).toMatch(/first_name:\s*`pulpo-locale:\$\{safeLocale\}`/);
  });

  it("treats Resend 'already exists' as success and flips unsubscribed=false", () => {
    // The dedup branch is what makes a re-upgrade (former Pro
    // unsubscribed, then re-paid) restore newsletter delivery.
    expect(helperSrc).toMatch(/already exists\|duplicate\|already subscribed/);
    expect(helperSrc).toMatch(/_setUnsubscribed\(\{[^}]*unsubscribed:\s*false/);
  });

  it("PATCHes contact by email on unsubscribe (preserves contact history)", () => {
    expect(helperSrc).toMatch(/method:\s*"PATCH"/);
    expect(helperSrc).toMatch(/audiences\/\$\{audienceId\}\/contacts\/\$\{encodeURIComponent\(email\)\}/);
    // Deliberately NOT DELETE — preserves analytics + reversibility
    expect(helperSrc).not.toMatch(/method:\s*"DELETE"/);
  });

  it("degrades to {ok:false, reason:'missing_config'} when secrets are missing", () => {
    expect(helperSrc).toMatch(/if \(!apiKey \|\| !audienceId\)/);
    expect(helperSrc).toMatch(/reason:\s*"missing_config"/);
  });

  it("never throws — all failure paths return a shape", () => {
    // Both helpers wrap fetch in try/catch and return {ok, reason}.
    const catchCount = (helperSrc.match(/} catch \(err\) \{/g) || []).length;
    expect(catchCount).toBeGreaterThanOrEqual(2);
  });
});

describe("api/stripe/webhook.js — Pro upgrade enroll sites", () => {
  it("imports the helper", () => {
    expect(webhookSrc).toMatch(/require\("\.\.\/_resend_audience"\)/);
    expect(webhookSrc).toMatch(/enrollPaidUserInAudience/);
    expect(webhookSrc).toMatch(/unsubscribeOnPlanLoss/);
  });

  it("enrolls on the auth-gated upgrade path", () => {
    expect(webhookSrc).toMatch(/source:\s*"stripe\.checkout\.auth_gated"/);
  });

  it("enrolls on the anonymous-existing-user path", () => {
    expect(webhookSrc).toMatch(/source:\s*"stripe\.checkout\.anonymous_existing_user"/);
  });

  it("enrolls on the anonymous-race-recovered path", () => {
    expect(webhookSrc).toMatch(/source:\s*"stripe\.checkout\.anonymous_race_recovered"/);
  });

  it("enrolls on the anonymous-new-user invitation path", () => {
    expect(webhookSrc).toMatch(/source:\s*"stripe\.checkout\.anonymous_new_user"/);
  });

  it("enroll calls are gated on email presence (not all 4 paths guarantee it)", () => {
    // At least one enroll site checks `if (email)` — auth_gated path
    // doesn't always have an email in scope. The 3 anonymous paths
    // gate naturally via the earlier `if (!email)` early-return.
    expect(webhookSrc).toMatch(/if \(email\)\s*\{\s*await enrollPaidUserInAudience/);
  });

  it("calls enrollPaidUserInAudience exactly 4 times (one per Pro-upgrade path)", () => {
    const enrollCalls = (webhookSrc.match(/await enrollPaidUserInAudience\(/g) || []).length;
    expect(enrollCalls).toBe(4);
  });
});

describe("api/stripe/webhook.js — subscription cancellation unsubscribe site", () => {
  it("unsubscribes on terminal subscription state (canceled / expired / deleted)", () => {
    // The isTerminal boolean gates the unsubscribe call — only fires
    // when the user is actually dropping out of Pro, not on grace-period
    // past_due states (where they're still entitled to newsletters).
    expect(webhookSrc).toMatch(/if \(isTerminal && subEmail\)\s*\{\s*await unsubscribeOnPlanLoss/);
  });

  it("unsubscribe call is exactly once (not in the active/grace paths)", () => {
    const unsubCalls = (webhookSrc.match(/await unsubscribeOnPlanLoss\(/g) || []).length;
    expect(unsubCalls).toBe(1);
  });

  it("source tag carries the event type for audit", () => {
    expect(webhookSrc).toMatch(/source:\s*`stripe\.\$\{event\.type\}`/);
  });
});

describe("scripts/backfill_resend_audience.mjs", () => {
  it("requires CLERK_SECRET_KEY + RESEND_API_KEY + RESEND_AUDIENCE_ID", () => {
    expect(backfillSrc).toMatch(/CLERK_SECRET_KEY/);
    expect(backfillSrc).toMatch(/RESEND_API_KEY/);
    expect(backfillSrc).toMatch(/RESEND_AUDIENCE_ID/);
    // All three exit 1 if missing — silent no-op would be a footgun
    const dieCount = (backfillSrc.match(/die\(/g) || []).length;
    expect(dieCount).toBeGreaterThanOrEqual(3);
  });

  it("supports --dry-run for safety", () => {
    expect(backfillSrc).toMatch(/--dry-run/);
    expect(backfillSrc).toMatch(/DRY_RUN\s*=\s*process\.argv\.includes\("--dry-run"\)/);
    // Dry run does NOT call the helper
    expect(backfillSrc).toMatch(/no Resend writes performed/);
  });

  it("filters Clerk users by plan ∈ {pro, agency}", () => {
    expect(backfillSrc).toMatch(/PRO_PLANS\s*=\s*new Set\(\["pro",\s*"agency"\]\)/);
    expect(backfillSrc).toMatch(/PRO_PLANS\.has\(plan\)/);
  });

  it("reuses the shared helper, not a duplicate enroll implementation", () => {
    expect(backfillSrc).toMatch(/enrollPaidUserInAudience/);
    expect(backfillSrc).not.toMatch(/fetch\(`https:\/\/api\.resend\.com\/audiences/);
  });

  it("logs per-user result + summary counts (enrolled / dedup / failed)", () => {
    expect(backfillSrc).toMatch(/enrolled=/);
    expect(backfillSrc).toMatch(/dedup=/);
    expect(backfillSrc).toMatch(/failed=/);
  });
});
