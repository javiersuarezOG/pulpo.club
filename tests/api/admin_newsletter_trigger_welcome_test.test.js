// Unit tests for /api/admin/newsletter/trigger-welcome-test.
//
// The endpoint now calls the SYNCHRONOUS internal dispatcher and returns
// its REAL outcome (sent / skipped / failed) — so the admin widget only
// confirms "Sent" when it actually sent. These tests pin that contract:
// the internal-call payload, the status passthrough, and the honest
// failure modes (no token / fetch error → status:"error", never "sent").

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import endpoint from "../../api/admin/newsletter/trigger-welcome-test.js";

const { handler } = endpoint;

function mockRes() {
  const res = { statusCode: 200, body: null, headers: {} };
  res.status = vi.fn((c) => { res.statusCode = c; return res; });
  res.json = vi.fn((b) => { res.body = b; return res; });
  res.setHeader = vi.fn((k, v) => { res.headers[k] = v; });
  return res;
}

let ipCounter = 0;
function mockReq(body) {
  ipCounter += 1;
  return { method: "POST", headers: { "x-forwarded-for": `10.0.0.${ipCounter}` }, body };
}

describe("trigger-welcome-test → internal endpoint", () => {
  const ORIGINAL = process.env.PULPO_INTERNAL_TOKEN;
  beforeEach(() => {
    process.env.PULPO_INTERNAL_TOKEN = "internal_test";
    process.env.PULPO_SITE_ROOT = "https://pulpo.club";
  });
  afterEach(() => {
    if (ORIGINAL === undefined) delete process.env.PULPO_INTERNAL_TOKEN;
    else process.env.PULPO_INTERNAL_TOKEN = ORIGINAL;
    delete process.env.PULPO_SITE_ROOT;
  });

  it("forwards email/source/force/variant/locale and returns status:sent", async () => {
    let captured = null;
    const fetchImpl = vi.fn(async (url, opts) => {
      captured = { url, body: JSON.parse(opts.body) };
      return { status: 200, json: async () => ({ status: "sent", message_id: "re_abc", dry_run: false, latency_ms: 1200 }) };
    });
    const res = mockRes();
    await handler(mockReq({ email: "me@pulpo.club", variant: "welcome_back", locale: "es" }), res, { fetchImpl });

    expect(captured.url).toBe("https://pulpo.club/api/internal/welcome-send");
    expect(captured.body).toEqual({ email: "me@pulpo.club", source: "admin", force: true, variant: "welcome_back", locale: "es" });
    expect(res.body.status).toBe("sent");
    expect(res.body.message_id).toBe("re_abc");
    expect(res.body.dry_run).toBe(false);
  });

  it("trims a whitespace-padded PULPO_INTERNAL_TOKEN before sending the bearer (the http_401 bug)", async () => {
    // A trailing newline on the Vercel env var must NOT reach the bearer —
    // the internal endpoint strips its side, so an un-trimmed bearer 401s.
    process.env.PULPO_INTERNAL_TOKEN = "secret_tok\n";
    let authHeader = null;
    const fetchImpl = vi.fn(async (url, opts) => {
      authHeader = opts.headers.Authorization;
      return { status: 200, json: async () => ({ status: "sent" }) };
    });
    const res = mockRes();
    await handler(mockReq({ email: "me@pulpo.club" }), res, { fetchImpl });
    expect(authHeader).toBe("Bearer secret_tok");
    expect(res.body.status).toBe("sent");
  });

  it("passes through a skip with its reason (NOT a false 'sent')", async () => {
    const fetchImpl = vi.fn(async () => ({ status: 200, json: async () => ({ status: "skipped", reason: "not_pro" }) }));
    const res = mockRes();
    await handler(mockReq({ email: "free@pulpo.club" }), res, { fetchImpl });
    expect(res.body.status).toBe("skipped");
    expect(res.body.reason).toBe("not_pro");
  });

  it("passes through a failure", async () => {
    const fetchImpl = vi.fn(async () => ({ status: 500, json: async () => ({ status: "failed", reason: "send_failed" }) }));
    const res = mockRes();
    await handler(mockReq({ email: "x@pulpo.club" }), res, { fetchImpl });
    expect(res.body.status).toBe("failed");
    expect(res.body.reason).toBe("send_failed");
  });

  it("omits locale from the payload when not en/es (→ dispatcher uses Clerk locale)", async () => {
    let captured = null;
    const fetchImpl = vi.fn(async (url, opts) => { captured = JSON.parse(opts.body); return { status: 200, json: async () => ({ status: "sent" }) }; });
    const res = mockRes();
    await handler(mockReq({ email: "x@pulpo.club" }), res, { fetchImpl });
    expect(captured).not.toHaveProperty("locale");
    expect(res.body.status).toBe("sent");
  });

  it("missing PULPO_INTERNAL_TOKEN → status:error, never calls the internal endpoint", async () => {
    delete process.env.PULPO_INTERNAL_TOKEN;
    const fetchImpl = vi.fn();
    const res = mockRes();
    await handler(mockReq({ email: "x@pulpo.club" }), res, { fetchImpl });
    expect(res.body.status).toBe("error");
    expect(res.body.reason).toBe("internal_endpoint_not_configured");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("internal fetch error → status:error (not a false 'sent')", async () => {
    const fetchImpl = vi.fn(async () => { throw new Error("ECONNREFUSED"); });
    const res = mockRes();
    await handler(mockReq({ email: "x@pulpo.club" }), res, { fetchImpl });
    expect(res.body.status).toBe("error");
    expect(String(res.body.reason)).toContain("fetch_failed");
  });

  it("rejects an invalid email before any internal call", async () => {
    const fetchImpl = vi.fn();
    const res = mockRes();
    await handler(mockReq({ email: "not-an-email" }), res, { fetchImpl });
    expect(res.statusCode).toBe(400);
    expect(res.body.reason).toBe("invalid_email");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
