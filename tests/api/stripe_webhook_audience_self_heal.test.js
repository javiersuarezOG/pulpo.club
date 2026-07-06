// Regression guard: the customer.subscription.updated handler must
// self-heal Resend audience membership for ACTIVE Pro subscriptions.
//
// Why this exists: audience enrollment used to live in exactly ONE place
// — the checkout.session.completed handler — where enrollPaidUserInAudience
// is best-effort + NON-retried. A transient Resend failure there (or any
// non-checkout route to Pro, e.g. a 100%-off friend-coupon redemption that
// hiccuped at enroll time) left a paying user plan=pro in Clerk but absent
// from the newsletter audience, so they silently never received the Pro
// weekly. This was a real prod miss (miguezablah@gmail.com, 2026-07).
//
// The fix wires enrollPaidUserInAudience into subscription.updated on the
// active/trialing path, which fires on the original checkout AND on every
// renewal/recovery — giving every active Pro repeated idempotent chances to
// land in the audience. This is a source-grep guard in the same spirit as
// stripe_webhook_field_coverage.test.js: the full handler integration is a
// Sebas-side Stripe-sandbox preview smoke per CLAUDE.md.

import { describe, expect, test } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const REPO_ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "../..");
const source = fs.readFileSync(path.join(REPO_ROOT, "api/stripe/webhook.js"), "utf8");

// Isolate the customer.subscription.updated / .deleted case body so the
// assertions can't be satisfied by the checkout.session.completed enroll
// calls elsewhere in the file.
function subscriptionCaseBody(src) {
  const start = src.indexOf('case "customer.subscription.updated":');
  expect(start).toBeGreaterThan(-1);
  const end = src.indexOf('case "invoice.payment_failed":', start);
  expect(end).toBeGreaterThan(start);
  return src.slice(start, end);
}

describe("subscription.updated self-heals Resend audience membership", () => {
  const caseBody = subscriptionCaseBody(source);

  test("calls enrollPaidUserInAudience inside the subscription handler", () => {
    expect(caseBody).toMatch(/enrollPaidUserInAudience\(/);
  });

  test("enrollment is gated on the active status, not fired on every event", () => {
    // The enroll must sit behind isActive so past_due / canceled events
    // don't (re)enroll a churned or dunning subscriber.
    expect(caseBody).toMatch(/if\s*\(\s*isActive\s*&&\s*subEmail\s*\)/);
  });

  test("tags the enroll with a self-heal source for observability", () => {
    expect(caseBody).toContain("stripe.subscription.active_self_heal");
  });

  test("surfaces the enroll outcome in the subscription_changed telemetry", () => {
    // `ok` on this property = a previously-missing Pro just got enrolled;
    // a stream of `ok` on renewals is the signal the checkout-time enroll
    // is dropping users. The property must be wired for that alert to work.
    expect(caseBody).toMatch(/audience_enroll:/);
  });
});
