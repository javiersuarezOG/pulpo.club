import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import endpoint from "../../api/admin/newsletter/trigger-free-welcome-test.js";

const { handler } = endpoint;

function mockRes() {
  const res = { statusCode: 200, body: null, headers: {} };
  res.status = vi.fn((c) => { res.statusCode = c; return res; });
  res.json = vi.fn((b) => { res.body = b; return res; });
  res.setHeader = vi.fn((k, v) => { res.headers[k] = v; });
  return res;
}

let ipCounter = 0;
function mockReq(body, headers = {}) {
  ipCounter += 1;
  return {
    method: "POST",
    headers: {
      "x-forwarded-for": `10.1.0.${ipCounter}`,
      authorization: "Bearer admin_test",
      ...headers,
    },
    body,
  };
}

describe("trigger-free-welcome-test → internal endpoint", () => {
  const ORIGINAL_INTERNAL = process.env.PULPO_INTERNAL_TOKEN;
  const ORIGINAL_ADMIN = process.env.PULPO_ADMIN_DEBUG_TOKEN;

  beforeEach(() => {
    process.env.PULPO_INTERNAL_TOKEN = "internal_test";
    process.env.PULPO_ADMIN_DEBUG_TOKEN = "admin_test";
    process.env.PULPO_SITE_ROOT = "https://pulpo.club";
  });

  afterEach(() => {
    if (ORIGINAL_INTERNAL === undefined) delete process.env.PULPO_INTERNAL_TOKEN;
    else process.env.PULPO_INTERNAL_TOKEN = ORIGINAL_INTERNAL;
    if (ORIGINAL_ADMIN === undefined) delete process.env.PULPO_ADMIN_DEBUG_TOKEN;
    else process.env.PULPO_ADMIN_DEBUG_TOKEN = ORIGINAL_ADMIN;
    delete process.env.PULPO_SITE_ROOT;
  });

  it("does NOT require an admin bearer token (admin surface is open by design)", async () => {
    // The PULPO_ADMIN_DEBUG_TOKEN gate was removed 2026-06-10. With no
    // Authorization header the endpoint must still proceed to the
    // internal send — never a 401.
    const fetchImpl = vi.fn(async () => ({
      status: 200, json: async () => ({ status: "sent", message_id: "re_x", dry_run: false }),
    }));
    const res = mockRes();
    await handler(mockReq({ email: "me@pulpo.club" }, { authorization: "" }), res, { fetchImpl });
    expect(res.statusCode).not.toBe(401);
    expect(res.body.status).toBe("sent");
  });

  it("forwards free welcome-back variant/locale and returns status:sent", async () => {
    let captured = null;
    const fetchImpl = vi.fn(async (url, opts) => {
      captured = { url, auth: opts.headers.Authorization, body: JSON.parse(opts.body) };
      return { status: 200, json: async () => ({ status: "sent", message_id: "re_free", dry_run: false, latency_ms: 900 }) };
    });
    const res = mockRes();
    await handler(mockReq({ email: "me@pulpo.club", variant: "free_welcome_back", locale: "es" }), res, { fetchImpl });

    expect(captured.url).toBe("https://pulpo.club/api/internal/free-welcome-send");
    expect(captured.auth).toBe("Bearer internal_test");
    expect(captured.body).toEqual({
      email: "me@pulpo.club",
      source: "admin",
      force: true,
      is_new_contact: true,
      variant: "free_welcome_back",
      locale: "es",
    });
    expect(res.body.status).toBe("sent");
    expect(res.body.message_id).toBe("re_free");
  });

  it("passes through skipped and failed outcomes without false sent", async () => {
    const skipped = mockRes();
    await handler(
      mockReq({ email: "skip@pulpo.club" }),
      skipped,
      { fetchImpl: vi.fn(async () => ({ status: 200, json: async () => ({ status: "skipped", reason: "ranked_missing" }) })) },
    );
    expect(skipped.body.status).toBe("skipped");
    expect(skipped.body.reason).toBe("ranked_missing");

    const failed = mockRes();
    await handler(
      mockReq({ email: "fail@pulpo.club" }),
      failed,
      { fetchImpl: vi.fn(async () => ({ status: 500, json: async () => ({ status: "failed", reason: "send_failed" }) })) },
    );
    expect(failed.body.status).toBe("failed");
    expect(failed.body.reason).toBe("send_failed");
  });
});
