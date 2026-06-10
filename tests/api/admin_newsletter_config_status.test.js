// Unit tests for /api/admin/newsletter/config-status — the live env
// probe behind the console's "Config & connections" strip. Asserts the
// presence-only status mapping (ok/warn/bad), that secret VALUES never
// leak into the response, and the dry-run send-mode parsing.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import configStatus from "../../api/admin/newsletter/config-status.js";

let ipc = 0;
function mockReq(method = "GET") {
  ipc += 1;
  return { method, headers: { "x-forwarded-for": `10.7.0.${ipc}` } };
}
function mockRes() {
  const res = { statusCode: 200, body: null, headers: {} };
  res.status = vi.fn((c) => { res.statusCode = c; return res; });
  res.json = vi.fn((b) => { res.body = b; return res; });
  res.setHeader = vi.fn((k, v) => { res.headers[k] = v; });
  return res;
}
function rowOf(res, id) {
  return (res.body.connections || []).find((c) => c.id === id);
}

const SECRET_KEYS = [
  "GITHUB_DISPATCH_TOKEN", "RESEND_API_KEY", "RESEND_AUDIENCE_ID",
  "CLERK_SECRET_KEY", "PULPO_INTERNAL_TOKEN",
  "POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID",
  "PULPO_NEWSLETTER_DRY_RUN", "GITHUB_DISPATCH_REPO", "GITHUB_DISPATCH_REF",
];

describe("/api/admin/newsletter/config-status", () => {
  const ORIG = {};
  beforeEach(() => {
    for (const k of SECRET_KEYS) ORIG[k] = process.env[k];
    for (const k of SECRET_KEYS) delete process.env[k];
  });
  afterEach(() => {
    for (const k of SECRET_KEYS) {
      if (ORIG[k] === undefined) delete process.env[k];
      else process.env[k] = ORIG[k];
    }
    vi.restoreAllMocks();
  });

  it("405s a non-GET", async () => {
    const res = mockRes();
    await configStatus(mockReq("POST"), res);
    expect(res.statusCode).toBe(405);
  });

  it("marks every required dependency bad when nothing is set", async () => {
    const res = mockRes();
    await configStatus(mockReq(), res);
    expect(res.statusCode).toBe(200);
    expect(rowOf(res, "github_dispatch").status).toBe("bad");
    expect(rowOf(res, "resend").status).toBe("bad");
    expect(rowOf(res, "clerk").status).toBe("bad");
    // Optional-but-recommended → warn, not bad.
    expect(rowOf(res, "internal_welcome").status).toBe("warn");
    expect(rowOf(res, "posthog_read").status).toBe("warn");
    expect(res.body.all_ready).toBe(false);
  });

  it("marks dependencies ok when configured + send mode LIVE by default", async () => {
    process.env.GITHUB_DISPATCH_TOKEN = "ghd_secret";
    process.env.RESEND_API_KEY = "re_secret";
    process.env.RESEND_AUDIENCE_ID = "aud_123";
    process.env.CLERK_SECRET_KEY = "sk_secret";
    process.env.PULPO_INTERNAL_TOKEN = "int_secret";
    process.env.POSTHOG_PERSONAL_API_KEY = "phk_secret";
    process.env.POSTHOG_PROJECT_ID = "999";
    const res = mockRes();
    await configStatus(mockReq(), res);
    expect(rowOf(res, "github_dispatch").status).toBe("ok");
    expect(rowOf(res, "resend").status).toBe("ok");
    expect(rowOf(res, "clerk").status).toBe("ok");
    expect(rowOf(res, "internal_welcome").status).toBe("ok");
    expect(rowOf(res, "posthog_read").status).toBe("ok");
    // No dry-run env → LIVE → ok.
    expect(rowOf(res, "send_mode").status).toBe("ok");
    expect(rowOf(res, "send_mode").detail).toMatch(/LIVE/);
    expect(res.body.all_ready).toBe(true);
  });

  it("flags send mode warn (DRY-RUN) for truthy PULPO_NEWSLETTER_DRY_RUN values", async () => {
    for (const v of ["1", "true", "yes", "on"]) {
      process.env.PULPO_NEWSLETTER_DRY_RUN = v;
      const res = mockRes();
      await configStatus(mockReq(), res);
      expect(rowOf(res, "send_mode").status).toBe("warn");
      expect(rowOf(res, "send_mode").detail).toMatch(/DRY-RUN/);
    }
  });

  it("names the EXACT missing var on a partially-configured dependency", async () => {
    // Personal API key set, numeric project id NOT — the row must point at
    // the one var that's actually missing, not a vague "read keys missing".
    process.env.POSTHOG_PERSONAL_API_KEY = "phx_set";
    const res = mockRes();
    await configStatus(mockReq(), res);
    const row = rowOf(res, "posthog_read");
    expect(row.detail).toBe("POSTHOG_PROJECT_ID missing");
    expect(row.detail).not.toMatch(/POSTHOG_PERSONAL_API_KEY/);
  });

  it("joins multiple missing vars with + in the detail", async () => {
    // Neither Resend var set → both named.
    const res = mockRes();
    await configStatus(mockReq(), res);
    expect(rowOf(res, "resend").detail).toBe("RESEND_API_KEY + RESEND_AUDIENCE_ID missing");
  });

  it("echoes the dispatch repo/ref but NEVER a secret value", async () => {
    process.env.GITHUB_DISPATCH_TOKEN = "ghd_TOPSECRET_value";
    process.env.GITHUB_DISPATCH_REPO = "acme/pulpo";
    process.env.GITHUB_DISPATCH_REF = "release";
    process.env.RESEND_API_KEY = "re_TOPSECRET_value";
    process.env.RESEND_AUDIENCE_ID = "aud_TOPSECRET";
    const res = mockRes();
    await configStatus(mockReq(), res);
    const serialized = JSON.stringify(res.body);
    // Non-sensitive identifiers are allowed through.
    expect(rowOf(res, "github_dispatch").detail).toMatch(/acme\/pulpo · release/);
    // Secret material must not appear anywhere in the payload.
    expect(serialized).not.toMatch(/TOPSECRET/);
  });
});
