// Shape regression for the two new admin newsletter endpoints:
//
//   api/admin/newsletter/audience-count.js
//   api/admin/newsletter/trigger-audience-send.js
//
// Both are auth-light per repo convention; the real security perimeter
// is GITHUB_DISPATCH_TOKEN + rate limits + (for the send endpoint) the
// SEND type-to-confirm gate. This file is the cheap reliable insurance
// that a refactor doesn't silently drop one of those gates.
//
// True behavioural coverage of the dispatch flow lives at the e2e
// admin widget click test (when it lands). This file mirrors the
// existing pattern at tests/api/saves_storage_shape.test.js +
// tests/api/update_profile_allowlist.test.js.

import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const COUNT_HANDLER = path.resolve(
  __dirname, "../../api/admin/newsletter/audience-count.js",
);
const SEND_HANDLER = path.resolve(
  __dirname, "../../api/admin/newsletter/trigger-audience-send.js",
);
const PREVIEW_HANDLER = path.resolve(
  __dirname, "../../api/admin/newsletter/trigger-preview.js",
);
const WELCOME_TEST_HANDLER = path.resolve(
  __dirname, "../../api/admin/newsletter/trigger-welcome-test.js",
);
const FREE_WELCOME_TEST_HANDLER = path.resolve(
  __dirname, "../../api/admin/newsletter/trigger-free-welcome-test.js",
);

const countSrc = fs.readFileSync(COUNT_HANDLER, "utf8");
const sendSrc = fs.readFileSync(SEND_HANDLER, "utf8");
const previewSrc = fs.readFileSync(PREVIEW_HANDLER, "utf8");
const welcomeTestSrc = fs.readFileSync(WELCOME_TEST_HANDLER, "utf8");
const freeWelcomeTestSrc = fs.readFileSync(FREE_WELCOME_TEST_HANDLER, "utf8");

describe("api/admin/newsletter/audience-count", () => {
  it("is GET-only", () => {
    expect(countSrc).toMatch(/req\.method !== "GET"/);
    expect(countSrc).toMatch(/method_not_allowed/);
  });

  it("intersects Resend audience with Clerk Pro/Agency users", () => {
    expect(countSrc).toMatch(/listResendAudienceEmails/);
    expect(countSrc).toMatch(/listClerkProEmails/);
    expect(countSrc).toMatch(/plan !== "pro" && plan !== "agency"/);
    expect(countSrc).toMatch(/resendEmails\.has\(email\)/);
  });

  it("excludes unsubscribed Resend contacts", () => {
    expect(countSrc).toMatch(/if \(r\.unsubscribed\) continue/);
  });

  it("rate-limits per IP at 30/min", () => {
    expect(countSrc).toMatch(/makeRateLimiter/);
    expect(countSrc).toMatch(/windowMs:\s*60_000/);
    expect(countSrc).toMatch(/maxAttempts:\s*30/);
  });

  it("returns count + diagnostic totals + computed_at", () => {
    expect(countSrc).toMatch(/count,/);
    expect(countSrc).toMatch(/resend_total/);
    expect(countSrc).toMatch(/clerk_pro_total/);
    expect(countSrc).toMatch(/computed_at/);
  });

  it("degrades to empty when secrets are missing (silent no-op)", () => {
    // Resend env vars
    expect(countSrc).toMatch(/if \(!RESEND_API_KEY \|\| !RESEND_AUDIENCE_ID\) return \[\]/);
    // Clerk env var
    expect(countSrc).toMatch(/if \(!CLERK_SECRET_KEY\) return new Set\(\)/);
  });
});

describe("api/admin/newsletter/trigger-audience-send", () => {
  it("is POST-only", () => {
    expect(sendSrc).toMatch(/req\.method !== "POST"/);
    expect(sendSrc).toMatch(/method_not_allowed/);
  });

  it("rate-limits to 1 send per IP per hour", () => {
    expect(sendSrc).toMatch(/makeRateLimiter/);
    expect(sendSrc).toMatch(/windowMs:\s*60\s*\*\s*60\s*\*\s*1000/);
    expect(sendSrc).toMatch(/maxAttempts:\s*1/);
  });

  it("rate-limit fires AFTER SEND + issue_number validation (not before)", () => {
    // Regression catch: the original v1 ordering put limiter.hit()
    // before the body-validation gates, which meant a typo on the
    // SEND input burned the 1-hour slot. The operator's next valid
    // attempt 429'd for an hour over a typo. Fix shipped in the
    // follow-up PR; this assertion makes sure no refactor moves the
    // limiter back ahead of validation.
    const confirmIdx = sendSrc.indexOf(`confirm !== REQUIRED_CONFIRM_STRING`);
    const issueNumIdx = sendSrc.indexOf(`issue_number_required`);
    const limiterHitIdx = sendSrc.indexOf(`limiter.hit(ip)`);
    expect(confirmIdx).toBeGreaterThan(-1);
    expect(issueNumIdx).toBeGreaterThan(-1);
    expect(limiterHitIdx).toBeGreaterThan(-1);
    expect(limiterHitIdx).toBeGreaterThan(confirmIdx);
    expect(limiterHitIdx).toBeGreaterThan(issueNumIdx);
  });

  it("requires the literal SEND confirm string (server-side mirror of the modal gate)", () => {
    expect(sendSrc).toMatch(/REQUIRED_CONFIRM_STRING\s*=\s*"SEND"/);
    expect(sendSrc).toMatch(/confirm !== REQUIRED_CONFIRM_STRING/);
    expect(sendSrc).toMatch(/confirm_required/);
  });

  it("requires issue_number (no default)", () => {
    expect(sendSrc).toMatch(/issue_number_required/);
    expect(sendSrc).toMatch(/body\.issue_number === undefined \|\| body\.issue_number === null/);
  });

  it("dispatches the workflow with send_mode=yes", () => {
    expect(sendSrc).toMatch(/send_mode:\s*"yes"/);
    expect(sendSrc).toMatch(/WORKFLOW_FILE\s*=\s*"pulpo-newsletter\.yml"/);
  });

  it("fires PostHog audit event with operator + result + audience_count", () => {
    expect(sendSrc).toMatch(/admin\.newsletter_audience_send_triggered/);
    expect(sendSrc).toMatch(/emitAuditEvent/);
    expect(sendSrc).toMatch(/audience_count: audienceCount/);
  });

  it("returns 503 when GITHUB_DISPATCH_TOKEN is missing", () => {
    expect(sendSrc).toMatch(/GITHUB_DISPATCH_TOKEN/);
    expect(sendSrc).toMatch(/github_dispatch_not_configured/);
  });

  it("emits audit event on failure paths too (not just success)", () => {
    // Three failure exits all hit emitAuditEvent before returning
    const auditCalls = (sendSrc.match(/await emitAuditEvent\(/g) || []).length;
    expect(auditCalls).toBeGreaterThanOrEqual(3);
  });
});

describe("api/admin/newsletter write endpoints auth", () => {
  it("single-recipient test endpoints stay open — no requireAdminAuth gate", () => {
    // Operator decision 2026-06-10: the PULPO_ADMIN_DEBUG_TOKEN gate was
    // removed from /admin. That decision still holds for the low-blast
    // single-recipient surfaces (preview + the two test-send triggers):
    // they email one operator-chosen address, so the open posture is an
    // accepted, bounded risk. This test pins that so a future
    // re-introduction of the gate on these is a deliberate, visible change.
    for (const src of [previewSrc, welcomeTestSrc, freeWelcomeTestSrc]) {
      expect(src).not.toMatch(/requireAdminAuth/);
    }
  });

  it("the full-audience blast IS bearer-gated (deliberate carve-out from open admin)", () => {
    // Operator decision (audit 2026-06-11): trigger-audience-send fires a
    // LIVE blast to the ENTIRE Pro audience. The public SEND string + per-IP
    // (cold-start-resettable) rate-limit are not sufficient for an unbounded
    // consent/reputation surface, so this one endpoint is re-gated with
    // requireAdminAuth while the single-recipient triggers stay open.
    expect(sendSrc).toMatch(/requireAdminAuth/);
  });

  it("the high-blast audience send keeps its type-to-confirm SEND gate", () => {
    // Removing auth does NOT remove the guardrail on the one path that
    // emails every Pro subscriber — the literal "SEND" confirm must stay.
    expect(sendSrc).toMatch(/SEND/);
  });

  it("free welcome tests use the dedicated synchronous endpoint, not the weekly preview workflow", () => {
    expect(freeWelcomeTestSrc).toMatch(/INTERNAL_PATH\s*=\s*"\/api\/internal\/free-welcome-send"/);
    expect(freeWelcomeTestSrc).toMatch(/variant === "free_welcome_back"/);
    expect(freeWelcomeTestSrc).toMatch(/is_new_contact:\s*true/);
  });
});
