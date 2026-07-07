// Unit tests for /api/admin/newsletter/health — the per-template
// deliverability aggregator. Mocks the PostHog HogQL response and asserts
// the bucketing: tier-split weekly, sent/skipped/failed per family, and
// the dry-run flag (true only when sends happened and none were real).

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import health from "../../api/admin/newsletter/health.js";

let ipc = 0;
function mockReq() {
  ipc += 1;
  return { method: "GET", headers: { "x-forwarded-for": `10.9.0.${ipc}` } };
}
function mockRes() {
  const res = { statusCode: 200, body: null, headers: {} };
  res.status = vi.fn((c) => { res.statusCode = c; return res; });
  res.json = vi.fn((b) => { res.body = b; return res; });
  res.setHeader = vi.fn((k, v) => { res.headers[k] = v; });
  return res;
}
function famOf(res, id) {
  return (res.body.families || []).find((f) => f.id === id);
}

const COLUMNS = ["event", "tier", "dry_run", "n", "last_at"];
function stubPostHog(results) {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ columns: COLUMNS, results }),
    text: async () => "",
  })));
}

describe("/api/admin/newsletter/health", () => {
  const ORIG = { key: process.env.POSTHOG_PERSONAL_API_KEY, proj: process.env.POSTHOG_PROJECT_ID };
  beforeEach(() => {
    process.env.POSTHOG_PERSONAL_API_KEY = "phk_test";
    process.env.POSTHOG_PROJECT_ID = "123";
  });
  afterEach(() => {
    process.env.POSTHOG_PERSONAL_API_KEY = ORIG.key;
    process.env.POSTHOG_PROJECT_ID = ORIG.proj;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("splits the weekly send by tier (pro/agency → pro-weekly, free/anon → free-weekly)", async () => {
    stubPostHog([
      ["newsletter.send_succeeded", "pro", false, 128, "2026-06-10T10:00:00Z"],
      ["newsletter.send_succeeded", "agency", false, 4, "2026-06-10T10:01:00Z"],
      ["newsletter.send_succeeded", "free", false, 9, "2026-06-10T09:00:00Z"],
      ["newsletter.send_succeeded", "anonymous", false, 6, "2026-06-10T09:01:00Z"],
      ["newsletter.send_failed", "free", null, 1, "2026-06-10T09:02:00Z"],
    ]);
    const res = mockRes();
    await health(mockReq(), res);
    expect(res.statusCode).toBe(200);
    expect(famOf(res, "pro-weekly").sent).toBe(132);   // 128 + 4
    expect(famOf(res, "free-weekly").sent).toBe(15);   // 9 + 6
    expect(famOf(res, "free-weekly").failed).toBe(1);
    expect(famOf(res, "pro-weekly").dry_run).toBe(false);
  });

  it("a tier-less weekly FAILURE surfaces on Pro (not silently hidden under Free) — P1", async () => {
    // Regression guard: a send_failed with a missing/empty tier used to
    // bucket under free-weekly, so a failed Pro campaign read as healthy.
    // It must now land on pro-weekly (the high-stakes family), never vanish.
    stubPostHog([
      ["newsletter.send_failed", null, null, 3, "2026-06-10T09:00:00Z"],
      ["newsletter.send_failed", "", null, 2, "2026-06-10T09:01:00Z"],
    ]);
    const res = mockRes();
    await health(mockReq(), res);
    expect(famOf(res, "pro-weekly").failed).toBe(5);   // 3 + 2 surfaced on Pro
    expect(famOf(res, "free-weekly").failed).toBe(0);  // NOT hidden here
  });

  it("buckets welcome / free-welcome events into sent/skipped/failed", async () => {
    stubPostHog([
      ["newsletter.welcome_sent", null, false, 6, "2026-06-10T08:00:00Z"],
      ["newsletter.welcome_skipped", null, null, 2, "2026-06-10T08:01:00Z"],
      ["newsletter.free_welcome_sent", null, false, 4, "2026-06-10T11:00:00Z"],
      ["newsletter.free_welcome_back_failed", null, null, 1, "2026-06-10T07:00:00Z"],
      ["email.invitation.sent", null, null, 19, "2026-06-10T11:30:00Z"],
    ]);
    const res = mockRes();
    await health(mockReq(), res);
    expect(famOf(res, "pro-welcome").sent).toBe(6);
    expect(famOf(res, "pro-welcome").skipped).toBe(2);
    expect(famOf(res, "free-welcome").sent).toBe(4);
    expect(famOf(res, "free-welcome-back").failed).toBe(1);
    expect(famOf(res, "activation").sent).toBe(19);
  });

  it("flags dry_run=true only when sends happened and none were real", async () => {
    stubPostHog([
      // free-welcome: only dry-run sends → dry_run true
      ["newsletter.free_welcome_sent", null, true, 4, "2026-06-10T11:00:00Z"],
      // pro-welcome: a real send present → dry_run false
      ["newsletter.welcome_sent", null, false, 1, "2026-06-10T10:00:00Z"],
      ["newsletter.welcome_sent", null, true, 3, "2026-06-10T10:05:00Z"],
    ]);
    const res = mockRes();
    await health(mockReq(), res);
    expect(famOf(res, "free-welcome").dry_run).toBe(true);
    expect(famOf(res, "pro-welcome").dry_run).toBe(false);
    // A family with no sends at all → dry_run null (idle, not "dry").
    expect(famOf(res, "free-weekly").dry_run).toBe(null);
  });

  it("graceful-degrades with unavailable_reason when PostHog env is missing", async () => {
    delete process.env.POSTHOG_PERSONAL_API_KEY;
    const res = mockRes();
    await health(mockReq(), res);
    expect(res.statusCode).toBe(200);
    expect(res.body.unavailable_reason).toMatch(/POSTHOG_PERSONAL_API_KEY/);
    // Still returns the full family list (blank rows) so the panel renders.
    expect(res.body.families.length).toBe(7);
  });
});
