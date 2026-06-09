// Homepage subscribe (api/newsletter.js) must fire the free-welcome email
// on a new contact, and the welcome-back on a re-subscribe — best-effort,
// via the internal Python dispatcher. A slow / failed / unconfigured
// dispatch must NEVER fail the subscribe itself.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import endpoint from "../../api/newsletter.js";

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
  return { method: "POST", headers: { "x-forwarded-for": `10.2.0.${ipCounter}` }, body };
}

function resendNewContact() {
  return { contacts: {
    create: vi.fn(async () => ({ data: { id: "c1" }, error: null })),
    update: vi.fn(async () => ({})),
  } };
}
function resendDuplicate() {
  return { contacts: {
    create: vi.fn(async () => ({ data: null, error: { name: "validation_error", message: "Contact already exists" } })),
    update: vi.fn(async () => ({ data: {}, error: null })),
  } };
}

describe("newsletter → free-welcome trigger", () => {
  const ORIGINAL = {
    token: process.env.PULPO_INTERNAL_TOKEN,
    root: process.env.PULPO_SITE_ROOT,
    key: process.env.RESEND_API_KEY,
    aud: process.env.RESEND_AUDIENCE_ID,
  };

  beforeEach(() => {
    process.env.RESEND_API_KEY = "re_test";
    process.env.RESEND_AUDIENCE_ID = "aud_test";
    process.env.PULPO_INTERNAL_TOKEN = "tok_test";
    process.env.PULPO_SITE_ROOT = "https://pulpo.test";
  });
  afterEach(() => {
    process.env.PULPO_INTERNAL_TOKEN = ORIGINAL.token;
    process.env.PULPO_SITE_ROOT = ORIGINAL.root;
    process.env.RESEND_API_KEY = ORIGINAL.key;
    process.env.RESEND_AUDIENCE_ID = ORIGINAL.aud;
    vi.restoreAllMocks();
  });

  it("new contact → fires free_welcome (source=signup) and still returns ok", async () => {
    const fetchImpl = vi.fn(async () => ({ status: 200, json: async () => ({ status: "sent", dry_run: true }) }));
    const res = mockRes();
    await handler(
      mockReq({ email: "New@Example.com ", locale: "en", source: "homepage_hero_v5" }),
      res,
      { fetchImpl, resendImpl: resendNewContact() },
    );
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://pulpo.test/api/internal/free-welcome-send");
    expect(opts.headers.Authorization).toBe("Bearer tok_test");
    const payload = JSON.parse(opts.body);
    expect(payload).toMatchObject({
      variant: "free_welcome", source: "signup", is_new_contact: true, locale: "en",
    });
  });

  it("re-subscribe (dedup) → fires free_welcome_back (source=resend_resubscribe)", async () => {
    const fetchImpl = vi.fn(async () => ({ status: 200, json: async () => ({ status: "sent" }) }));
    const res = mockRes();
    await handler(
      mockReq({ email: "back@example.com", locale: "es" }),
      res,
      { fetchImpl, resendImpl: resendDuplicate() },
    );
    expect(res.body).toEqual({ ok: true, resubscribed: true });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const payload = JSON.parse(fetchImpl.mock.calls[0][1].body);
    expect(payload).toMatchObject({ variant: "free_welcome_back", source: "resend_resubscribe", locale: "es" });
  });

  it("dispatch failure is best-effort — subscribe still succeeds", async () => {
    const fetchImpl = vi.fn(async () => { throw new Error("network down"); });
    const res = mockRes();
    await handler(
      mockReq({ email: "x@example.com", locale: "en" }),
      res,
      { fetchImpl, resendImpl: resendNewContact() },
    );
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ ok: true });
  });

  it("no PULPO_INTERNAL_TOKEN → skips dispatch, still subscribes", async () => {
    delete process.env.PULPO_INTERNAL_TOKEN;
    const fetchImpl = vi.fn();
    const res = mockRes();
    await handler(
      mockReq({ email: "y@example.com", locale: "en" }),
      res,
      { fetchImpl, resendImpl: resendNewContact() },
    );
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ ok: true });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
