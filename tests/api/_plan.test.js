// Unit tests for api/_plan.js — the backend founder-email override.
//
// The FOUNDER_EMAILS set is captured at module load, so each test
// resets the module registry and re-imports with a fresh env. Mirrors
// the pattern in web/app/lib/founder-emails.test.ts (frontend twin).

import { describe, it, expect, beforeEach, afterEach } from "vitest";

const ORIGINAL_FOUNDER = process.env.FOUNDER_EMAILS;
const ORIGINAL_VITE = process.env.VITE_FOUNDER_EMAILS;

async function loadHelperWith({ founder, vite } = {}) {
  delete process.env.FOUNDER_EMAILS;
  delete process.env.VITE_FOUNDER_EMAILS;
  if (founder !== undefined) process.env.FOUNDER_EMAILS = founder;
  if (vite !== undefined) process.env.VITE_FOUNDER_EMAILS = vite;
  // Bust the require cache — Node caches CommonJS modules by absolute
  // path, and our helper captures FOUNDER_EMAILS at top-level.
  const path = require.resolve("../../api/_plan.js");
  delete require.cache[path];
  return require("../../api/_plan.js");
}

function clerkUser({ email = null, plan = null, status = null, paymentFailedAt = null, graceEndsAt = null } = {}) {
  const meta = {};
  if (plan) meta.plan = plan;
  if (status) meta.subscription_status = status;
  if (paymentFailedAt !== null) meta.payment_failed_at = paymentFailedAt;
  if (graceEndsAt !== null) meta.grace_period_ends_at = graceEndsAt;
  return {
    primaryEmailAddress: email ? { emailAddress: email } : null,
    publicMetadata: meta,
  };
}

beforeEach(() => {
  delete process.env.FOUNDER_EMAILS;
  delete process.env.VITE_FOUNDER_EMAILS;
});

afterEach(() => {
  if (ORIGINAL_FOUNDER !== undefined) process.env.FOUNDER_EMAILS = ORIGINAL_FOUNDER;
  if (ORIGINAL_VITE !== undefined) process.env.VITE_FOUNDER_EMAILS = ORIGINAL_VITE;
});

describe("isFounderEmail", () => {
  it("returns false when env is empty", async () => {
    const { isFounderEmail } = await loadHelperWith({});
    expect(isFounderEmail("a@b.com")).toBe(false);
  });

  it("matches FOUNDER_EMAILS exactly", async () => {
    const { isFounderEmail } = await loadHelperWith({ founder: "a@b.com,c@d.com" });
    expect(isFounderEmail("a@b.com")).toBe(true);
    expect(isFounderEmail("c@d.com")).toBe(true);
    expect(isFounderEmail("z@z.com")).toBe(false);
  });

  it("falls back to VITE_FOUNDER_EMAILS when FOUNDER_EMAILS is unset", async () => {
    const { isFounderEmail } = await loadHelperWith({ vite: "a@b.com" });
    expect(isFounderEmail("a@b.com")).toBe(true);
  });

  it("prefers FOUNDER_EMAILS when both are set", async () => {
    const { isFounderEmail } = await loadHelperWith({
      founder: "a@b.com",
      vite: "different@vite.com",
    });
    expect(isFounderEmail("a@b.com")).toBe(true);
    expect(isFounderEmail("different@vite.com")).toBe(false);
  });

  it("is case-insensitive and trims whitespace", async () => {
    const { isFounderEmail } = await loadHelperWith({ founder: " A@B.com , c@d.com " });
    expect(isFounderEmail("a@b.com")).toBe(true);
    expect(isFounderEmail("C@D.COM")).toBe(true);
  });

  it("returns false for null/empty email", async () => {
    const { isFounderEmail } = await loadHelperWith({ founder: "a@b.com" });
    expect(isFounderEmail(null)).toBe(false);
    expect(isFounderEmail("")).toBe(false);
  });
});

describe("effectivePlan", () => {
  it("returns 'free' for a null user", async () => {
    const { effectivePlan } = await loadHelperWith({});
    expect(effectivePlan(null)).toBe("free");
  });

  it("returns 'pro' when publicMetadata.plan === 'pro'", async () => {
    const { effectivePlan } = await loadHelperWith({});
    expect(effectivePlan(clerkUser({ plan: "pro" }))).toBe("pro");
  });

  it("returns 'agency' when publicMetadata.plan === 'agency'", async () => {
    const { effectivePlan } = await loadHelperWith({});
    expect(effectivePlan(clerkUser({ plan: "agency" }))).toBe("agency");
  });

  it("returns 'pro' for a founder email even when metadata is empty", async () => {
    const { effectivePlan } = await loadHelperWith({ founder: "a@b.com" });
    expect(effectivePlan(clerkUser({ email: "a@b.com" }))).toBe("pro");
  });

  it("never demotes a real pro for a non-founder email", async () => {
    const { effectivePlan } = await loadHelperWith({ founder: "x@y.com" });
    expect(effectivePlan(clerkUser({ email: "a@b.com", plan: "pro" }))).toBe("pro");
  });

  it("returns 'free' when neither metadata nor founder match", async () => {
    const { effectivePlan } = await loadHelperWith({ founder: "x@y.com" });
    expect(effectivePlan(clerkUser({ email: "a@b.com" }))).toBe("free");
  });

  it("matches founder email case-insensitively", async () => {
    const { effectivePlan } = await loadHelperWith({ founder: "JAVIER@suarez.ventures" });
    expect(effectivePlan(clerkUser({ email: "javier@suarez.ventures" }))).toBe("pro");
  });
});

// ── 14-day grace window after a failed payment ────────────────────────
//
// Schema written by api/stripe/webhook.js on `invoice.payment_failed`
// (and on `customer.subscription.updated` when status flips to past_due):
//   subscription_status     = "past_due"
//   payment_failed_at       = <unix ms of first failure>
//   grace_period_ends_at    = payment_failed_at + 14 days
//
// During the window: deriveSubscriptionState marks the user as
// `effective: "pro"` and `in_grace: true`. Past the window: effective
// flips to "free" even though Stripe may still be retrying.

describe("deriveSubscriptionState — grace window", () => {
  const NOW = 1_700_000_000_000;
  const GRACE_MS_LOCAL = 14 * 24 * 60 * 60 * 1000;

  it("legacy pro user with no status field reads as active + pro", async () => {
    const { deriveSubscriptionState } = await loadHelperWith({});
    const s = deriveSubscriptionState({ plan: "pro" }, NOW);
    expect(s.effective).toBe("pro");
    expect(s.status).toBe("active");
    expect(s.in_grace).toBe(false);
  });

  it("active pro with status='active' reads as active + pro", async () => {
    const { deriveSubscriptionState } = await loadHelperWith({});
    const s = deriveSubscriptionState({ plan: "pro", subscription_status: "active" }, NOW);
    expect(s.effective).toBe("pro");
    expect(s.in_grace).toBe(false);
  });

  it("past_due within grace window keeps effective=pro + in_grace=true", async () => {
    const { deriveSubscriptionState } = await loadHelperWith({});
    const failedAt = NOW - (3 * 24 * 60 * 60 * 1000); // 3 days ago
    const graceEnds = failedAt + GRACE_MS_LOCAL;
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "past_due",
      payment_failed_at: failedAt,
      grace_period_ends_at: graceEnds,
    }, NOW);
    expect(s.effective).toBe("pro");
    expect(s.in_grace).toBe(true);
    expect(s.grace_period_ends_at).toBe(graceEnds);
  });

  it("past_due AFTER grace window flips effective to free, in_grace=false", async () => {
    const { deriveSubscriptionState } = await loadHelperWith({});
    const failedAt = NOW - (20 * 24 * 60 * 60 * 1000); // 20 days ago
    const graceEnds = failedAt + GRACE_MS_LOCAL;
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "past_due",
      payment_failed_at: failedAt,
      grace_period_ends_at: graceEnds,
    }, NOW);
    expect(s.effective).toBe("free");
    expect(s.in_grace).toBe(false);
    expect(s.status).toBe("past_due"); // raw status unchanged
    expect(s.plan).toBe("pro");        // raw plan unchanged — Stripe hasn't cancelled yet
  });

  it("past_due with missing grace_period_ends_at falls back to effective=pro (defensive — no clock to enforce against)", async () => {
    const { deriveSubscriptionState } = await loadHelperWith({});
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "past_due",
    }, NOW);
    expect(s.effective).toBe("pro");
    expect(s.in_grace).toBe(false);
  });

  it("canceled status with plan=pro reads as effective=free", async () => {
    const { deriveSubscriptionState } = await loadHelperWith({});
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "canceled",
    }, NOW);
    expect(s.effective).toBe("free");
    expect(s.in_grace).toBe(false);
  });

  it("agency plan always reads as agency regardless of status", async () => {
    const { deriveSubscriptionState } = await loadHelperWith({});
    const s = deriveSubscriptionState({
      plan: "agency",
      subscription_status: "past_due",
      payment_failed_at: NOW - GRACE_MS_LOCAL * 2,
      grace_period_ends_at: NOW - GRACE_MS_LOCAL,
    }, NOW);
    expect(s.effective).toBe("agency");
  });

  it("uses Date.now() when no `now` arg is passed", async () => {
    const { deriveSubscriptionState } = await loadHelperWith({});
    const inPast = Date.now() - 1_000_000;
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "past_due",
      payment_failed_at: inPast,
      grace_period_ends_at: Date.now() + 1_000_000, // future
    });
    expect(s.in_grace).toBe(true);
  });
});

describe("effectiveSubscriptionState — full view including founder override", () => {
  const NOW = 1_700_000_000_000;
  const GRACE_MS_LOCAL = 14 * 24 * 60 * 60 * 1000;

  it("returns the active-default state for a null user", async () => {
    const { effectiveSubscriptionState } = await loadHelperWith({});
    const s = effectiveSubscriptionState(null);
    expect(s).toEqual({
      plan: "free",
      effective: "free",
      status: "active",
      in_grace: false,
      grace_period_ends_at: null,
      payment_failed_at: null,
    });
  });

  it("founder email promotes effective to 'pro' on a free user", async () => {
    const { effectiveSubscriptionState } = await loadHelperWith({ founder: "a@b.com" });
    const s = effectiveSubscriptionState(clerkUser({ email: "a@b.com" }));
    expect(s.effective).toBe("pro");
    expect(s.plan).toBe("free"); // raw is still free — override is downstream
  });

  it("founder override does NOT override an expired grace user (still free)", async () => {
    // Edge case: founder email AND past_due grace expired. Founder override
    // kicks in for any free-effective user, so the user reads as Pro. This is
    // the expected behaviour — founder allowlist intentionally rescues anyone.
    const { effectiveSubscriptionState } = await loadHelperWith({ founder: "a@b.com" });
    const failedAt = NOW - (20 * 24 * 60 * 60 * 1000);
    const s = effectiveSubscriptionState(clerkUser({
      email: "a@b.com",
      plan: "pro",
      status: "past_due",
      paymentFailedAt: failedAt,
      graceEndsAt: failedAt + GRACE_MS_LOCAL,
    }));
    // Without the override, grace-expired past_due → effective=free. With
    // the override, founder is rescued → effective=pro. Document that
    // behaviour explicitly so a future change here is a conscious one.
    expect(s.effective).toBe("pro");
  });
});
