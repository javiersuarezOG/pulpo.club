// Unit tests for the P1-3 free/email-funnel attribution added to
// api/newsletter.js — the UTM allow-list (pickUtms) + the non-blocking
// contract of the server-side newsletter.signup telemetry.
// Runs under vitest (`npm test`). Real Resend/PostHog never get called.

import { describe, it, expect } from "vitest";
import { pickUtms, fireSignupTelemetry } from "../../api/newsletter.js";

describe("pickUtms — UTM allow-list for newsletter attribution (P1-3)", () => {
  it("passes the 5 known UTM keys through unchanged", () => {
    const out = pickUtms({
      utm_source: "google", utm_medium: "cpc", utm_campaign: "may_launch",
      utm_term: "beach+land", utm_content: "hero_a",
    });
    expect(out).toEqual({
      utm_source: "google", utm_medium: "cpc", utm_campaign: "may_launch",
      utm_term: "beach+land", utm_content: "hero_a",
    });
  });

  it("drops unknown keys — no arbitrary prop injection onto the Person", () => {
    // A malicious/buggy client must not be able to smuggle `$set`, plan
    // overrides, or free-form props onto the PostHog person via body.utms.
    expect(pickUtms({ utm_source: "x", $set: { plan: "pro" }, evil: "1", admin: true }))
      .toEqual({ utm_source: "x" });
  });

  it("ignores non-string and empty values", () => {
    expect(pickUtms({ utm_source: 123, utm_medium: "", utm_campaign: null, utm_term: {} }))
      .toEqual({});
  });

  it("caps long values at 200 chars (compact Person props)", () => {
    const out = pickUtms({ utm_campaign: "a".repeat(500) });
    expect(out.utm_campaign.length).toBe(200);
  });

  it("tolerates non-object input without throwing", () => {
    expect(pickUtms(null)).toEqual({});
    expect(pickUtms(undefined)).toEqual({});
    expect(pickUtms("nope")).toEqual({});
    expect(pickUtms(42)).toEqual({});
  });
});

describe("fireSignupTelemetry — never blocks the subscribe (P1-3)", () => {
  it("resolves without throwing when PostHog is unconfigured", async () => {
    // POSTHOG_PROJECT_TOKEN is unset in the test env, so capture()/flush()
    // are silent no-ops. The subscribe response must never depend on
    // telemetry, so the helper must resolve cleanly regardless.
    await expect(fireSignupTelemetry({
      email: "buyer@example.com", source: "homepage_hero", locale: "en",
      utms: { utm_source: "google", utm_campaign: "may" }, status: "new",
    })).resolves.toBeUndefined();
  });

  it("resolves even with no utms / missing fields", async () => {
    await expect(fireSignupTelemetry({ email: "x@y.com", status: "already" }))
      .resolves.toBeUndefined();
  });
});
