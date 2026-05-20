// Unit tests for the frontend deriveSubscriptionState — parity with
// api/_plan.js. If this file goes red, the Account-page grace banner
// will disagree with the backend's effective-plan derivation.

import { describe, it, expect } from "vitest";
import { deriveSubscriptionState, graceDaysLeft } from "./subscription";

const NOW = 1_700_000_000_000;
const DAY = 24 * 60 * 60 * 1000;
const GRACE_MS = 14 * DAY;

describe("deriveSubscriptionState", () => {
  it("null user → active default", () => {
    const s = deriveSubscriptionState(null, NOW);
    expect(s).toEqual({
      plan: "free",
      effective: "free",
      status: "active",
      in_grace: false,
      grace_period_ends_at: null,
      payment_failed_at: null,
    });
  });

  it("free user with no other fields → free + active", () => {
    const s = deriveSubscriptionState({ plan: "free" }, NOW);
    expect(s.effective).toBe("free");
    expect(s.status).toBe("active");
    expect(s.in_grace).toBe(false);
  });

  it("legacy pro user (no status field) reads as effective=pro + active", () => {
    const s = deriveSubscriptionState({ plan: "pro" }, NOW);
    expect(s.effective).toBe("pro");
    expect(s.status).toBe("active");
    expect(s.in_grace).toBe(false);
  });

  it("active pro + status=active → effective=pro, no grace", () => {
    const s = deriveSubscriptionState({ plan: "pro", subscription_status: "active" }, NOW);
    expect(s.effective).toBe("pro");
    expect(s.in_grace).toBe(false);
  });

  it("past_due within grace window: effective=pro, in_grace=true", () => {
    const failedAt = NOW - 3 * DAY;
    const graceEnds = failedAt + GRACE_MS;
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

  it("past_due AFTER grace window flips effective to free", () => {
    const failedAt = NOW - 20 * DAY;
    const graceEnds = failedAt + GRACE_MS;
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "past_due",
      payment_failed_at: failedAt,
      grace_period_ends_at: graceEnds,
    }, NOW);
    expect(s.effective).toBe("free");
    expect(s.in_grace).toBe(false);
    expect(s.plan).toBe("pro");      // raw unchanged
    expect(s.status).toBe("past_due"); // raw unchanged
  });

  it("canceled status with plan=pro reads as free", () => {
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "canceled",
    }, NOW);
    expect(s.effective).toBe("free");
    expect(s.in_grace).toBe(false);
  });

  it("agency always reads as agency, ignoring status", () => {
    const s = deriveSubscriptionState({
      plan: "agency",
      subscription_status: "past_due",
      payment_failed_at: NOW - GRACE_MS * 2,
      grace_period_ends_at: NOW - GRACE_MS,
    }, NOW);
    expect(s.effective).toBe("agency");
  });

  it("normalizes unknown subscription_status to 'active'", () => {
    const s = deriveSubscriptionState({
      plan: "pro",
      // @ts-expect-error — testing defensive normalization
      subscription_status: "ZZZZ",
    }, NOW);
    expect(s.status).toBe("active");
    expect(s.effective).toBe("pro");
  });
});

describe("graceDaysLeft", () => {
  it("returns 0 when user is not in grace", () => {
    expect(graceDaysLeft({ plan: "pro", subscription_status: "active" }, NOW)).toBe(0);
  });

  it("counts remaining days during grace", () => {
    const failedAt = NOW - 4 * DAY; // 4 days into grace
    const graceEnds = failedAt + GRACE_MS;
    expect(graceDaysLeft({
      plan: "pro",
      subscription_status: "past_due",
      payment_failed_at: failedAt,
      grace_period_ends_at: graceEnds,
    }, NOW)).toBe(10); // 14 - 4
  });

  it("returns 0 once grace expires", () => {
    const failedAt = NOW - 20 * DAY;
    const graceEnds = failedAt + GRACE_MS;
    expect(graceDaysLeft({
      plan: "pro",
      subscription_status: "past_due",
      payment_failed_at: failedAt,
      grace_period_ends_at: graceEnds,
    }, NOW)).toBe(0);
  });
});
