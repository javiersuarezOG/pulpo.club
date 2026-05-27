// Unit tests for the frontend deriveSubscriptionState — parity with
// api/_plan.js. If this file goes red, the Account-page grace banner
// will disagree with the backend's effective-plan derivation.

import { describe, it, expect } from "vitest";
import { deriveSubscriptionState, graceDaysLeft } from "./subscription";
import { t } from "../i18n.jsx";

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
      display: "active",
      current_period_end: null,
      cancel_at_period_end: false,
      canceled_at: null,
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

  // Sub-state display rules (post-2026-05-27 bug fix — pro user canceled
  // via Stripe portal must NEVER see "Renews on..." copy in the UI).
  it("active pro + cancel_at_period_end=true → display='canceling'", () => {
    const periodEnd = NOW + 10 * DAY;
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "active",
      cancel_at_period_end: true,
      current_period_end: periodEnd,
    }, NOW);
    expect(s.display).toBe("canceling");
    expect(s.effective).toBe("pro");           // still Pro until period_end
    expect(s.current_period_end).toBe(periodEnd);
    expect(s.cancel_at_period_end).toBe(true);
  });

  it("active pro + cancel_at_period_end=false → display='active'", () => {
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "active",
      cancel_at_period_end: false,
      current_period_end: NOW + 30 * DAY,
    }, NOW);
    expect(s.display).toBe("active");
  });

  it("canceled status → display='canceled'", () => {
    const canceledAt = NOW - 1 * DAY;
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "canceled",
      canceled_at: canceledAt,
    }, NOW);
    expect(s.display).toBe("canceled");
    expect(s.canceled_at).toBe(canceledAt);
  });

  it("past_due + inside grace → display='grace'", () => {
    const failedAt = NOW - 3 * DAY;
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "past_due",
      payment_failed_at: failedAt,
      grace_period_ends_at: failedAt + GRACE_MS,
    }, NOW);
    expect(s.display).toBe("grace");
  });

  it("past_due + grace expired → display='past_due'", () => {
    const failedAt = NOW - 20 * DAY;
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "past_due",
      payment_failed_at: failedAt,
      grace_period_ends_at: failedAt + GRACE_MS,
    }, NOW);
    expect(s.display).toBe("past_due");
  });

  it("cancel_at_period_end=true with status=canceled prioritizes 'canceled'", () => {
    // Edge: if both flags fire (Stripe completing the cancellation), the
    // terminal 'canceled' state wins over the pending 'canceling'.
    const s = deriveSubscriptionState({
      plan: "pro",
      subscription_status: "canceled",
      cancel_at_period_end: true,
      canceled_at: NOW - 1 * DAY,
    }, NOW);
    expect(s.display).toBe("canceled");
  });
});

// Canary: the post-2026-05-27 bug had "Renews on 5 Jun 2026" hardcoded
// in account.jsx — telling EVERY customer including canceled ones that
// their subscription would renew. These assertions guarantee that no
// future copy edit can re-introduce "Renews on" / "Se renueva" wording
// into the canceling or canceled display state's i18n entries. If you
// see this test fail, fix the copy — don't relax the assertion.
describe("subscription i18n copy contracts (anti-renewal-leak canary)", () => {
  const SAMPLE_DATE_EN = "27 June 2026";
  const SAMPLE_DATE_ES = "27 de junio de 2026";

  const RENEW_TOKENS = ["Renews on", "renews on", "Se renueva", "se renueva"];
  const CANCEL_TOKENS = ["Cancels on", "cancels on", "Se cancela", "se cancela"];
  const ENDED_TOKENS  = ["ended on", "Subscription ended", "finalizada", "Suscripción finalizada", "terminó"];

  function none(s: string, tokens: string[]) {
    for (const tok of tokens) {
      if (s.includes(tok)) return tok;
    }
    return null;
  }
  function any(s: string, tokens: string[]) {
    for (const tok of tokens) {
      if (s.includes(tok)) return true;
    }
    return false;
  }

  it("canceling plan_meta copy says 'Cancels on' but NEVER 'Renews on' (EN)", () => {
    const s = t("account.sub.plan_meta.cancels_on", "en", { date: SAMPLE_DATE_EN });
    expect(any(s, CANCEL_TOKENS)).toBe(true);
    expect(none(s, RENEW_TOKENS)).toBe(null);
  });

  it("canceling plan_meta copy says 'Se cancela' but NEVER 'Se renueva' (ES)", () => {
    const s = t("account.sub.plan_meta.cancels_on", "es", { date: SAMPLE_DATE_ES });
    expect(any(s, CANCEL_TOKENS)).toBe(true);
    expect(none(s, RENEW_TOKENS)).toBe(null);
  });

  it("canceling status_copy (EN) NEVER contains 'Renews on'", () => {
    const s = t("account.sub.status_copy.canceling", "en", { date: SAMPLE_DATE_EN });
    expect(none(s, RENEW_TOKENS)).toBe(null);
  });

  it("canceling status_copy (ES) NEVER contains 'Se renueva'", () => {
    const s = t("account.sub.status_copy.canceling", "es", { date: SAMPLE_DATE_ES });
    expect(none(s, RENEW_TOKENS)).toBe(null);
  });

  it("canceled status_copy (EN) NEVER contains 'Renews on'", () => {
    const s = t("account.sub.status_copy.canceled", "en", { date: SAMPLE_DATE_EN });
    expect(any(s, ENDED_TOKENS)).toBe(true);
    expect(none(s, RENEW_TOKENS)).toBe(null);
  });

  it("canceled status_copy (ES) NEVER contains 'Se renueva'", () => {
    const s = t("account.sub.status_copy.canceled", "es", { date: SAMPLE_DATE_ES });
    expect(any(s, ENDED_TOKENS)).toBe(true);
    expect(none(s, RENEW_TOKENS)).toBe(null);
  });

  it("active plan_meta copy (EN) contains 'Renews on' AND NEVER 'Cancels on'", () => {
    const s = t("account.sub.plan_meta.renews_on", "en", { date: SAMPLE_DATE_EN });
    expect(any(s, RENEW_TOKENS)).toBe(true);
    expect(none(s, CANCEL_TOKENS)).toBe(null);
    expect(none(s, ENDED_TOKENS)).toBe(null);
  });

  it("active plan_meta copy (ES) contains 'Se renueva' AND NEVER 'Se cancela'", () => {
    const s = t("account.sub.plan_meta.renews_on", "es", { date: SAMPLE_DATE_ES });
    expect(any(s, RENEW_TOKENS)).toBe(true);
    expect(none(s, CANCEL_TOKENS)).toBe(null);
    expect(none(s, ENDED_TOKENS)).toBe(null);
  });

  it("grace copy contains expiration language in EN + ES", () => {
    const en = t("account.sub.grace.copy", "en", { days: 3, date: SAMPLE_DATE_EN });
    const es = t("account.sub.grace.copy", "es", { days: 3, date: SAMPLE_DATE_ES });
    expect(en).toContain("expires");
    expect(es).toContain("vence");
  });

  it("date placeholder gets interpolated into every variant (EN)", () => {
    for (const key of [
      "account.sub.plan_meta.renews_on",
      "account.sub.plan_meta.cancels_on",
      "account.sub.plan_meta.ended_on",
      "account.sub.status_copy.active",
      "account.sub.status_copy.canceling",
      "account.sub.status_copy.canceled",
    ]) {
      const s = t(key, "en", { date: SAMPLE_DATE_EN });
      expect(s).toContain(SAMPLE_DATE_EN);
      // Smoke check: no unresolved placeholder.
      expect(s).not.toMatch(/\{date\}/);
    }
  });

  it("status pill labels exist for every display state (EN + ES)", () => {
    for (const lc of ["en", "es"]) {
      for (const state of ["active", "canceling", "canceled", "past_due"]) {
        const s = t(`account.sub.pill.${state}`, lc);
        expect(s).toBeTruthy();
        expect(s).not.toMatch(/\{|\}/);  // no unresolved placeholders
      }
    }
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
