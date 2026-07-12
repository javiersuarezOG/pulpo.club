// api/newsletter-prefs.js — the login-free "Change filters" endpoint for
// email-only free subscribers. Token IS the auth (no session), so the token
// gate and input sanitization are the security surface — test them hard.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import ep from "../../api/newsletter-prefs.js";

const ORIG = {};
beforeEach(() => {
  for (const k of ["PULPO_UNSUBSCRIBE_SECRET", "PULPO_NEWSLETTER_SALT", "RESEND_API_KEY", "RESEND_AUDIENCE_ID"]) ORIG[k] = process.env[k];
  process.env.PULPO_UNSUBSCRIBE_SECRET = "test_secret";
  process.env.PULPO_NEWSLETTER_SALT = "test_salt";
  process.env.RESEND_API_KEY = "re_test";
  process.env.RESEND_AUDIENCE_ID = "aud_test";
});
afterEach(() => {
  for (const k of Object.keys(ORIG)) { if (ORIG[k] === undefined) delete process.env[k]; else process.env[k] = ORIG[k]; }
  vi.restoreAllMocks();
});

function mockRes() {
  const res = { statusCode: 200, body: null, headers: {} };
  res.status = vi.fn((c) => { res.statusCode = c; return res; });
  res.send = vi.fn((b) => { res.body = b; return res; });
  res.json = vi.fn((b) => { res.body = b; return res; });
  res.setHeader = vi.fn((k, v) => { res.headers[k] = v; });
  return res;
}

const EMAIL = "tester@example.com";
function hash() { return ep.hashEmail(EMAIL); }
function goodToken(i = 2) { return ep.expectedToken(hash(), i); }

describe("token gate", () => {
  it("verifyToken accepts a matching token and rejects a forged one", () => {
    const r = hash();
    expect(ep.verifyToken(r, 2, goodToken())).toBe(true);
    expect(ep.verifyToken(r, 2, "0".repeat(32))).toBe(false);
    expect(ep.verifyToken(r, 2, "")).toBe(false);
    expect(ep.verifyToken(r, 3, goodToken(2))).toBe(false); // issue number is signed
  });

  it("GET with a bad token returns a 403 invalid page (no Resend call)", async () => {
    const res = mockRes();
    await ep({ method: "GET", query: { r: hash(), i: "2", t: "bogus", l: "en" } }, res);
    expect(res.statusCode).toBe(403);
    expect(res.headers["Content-Type"]).toMatch(/text\/html/);
    expect(res.body).toContain("expired");
  });

  it("rejects a missing token", async () => {
    const res = mockRes();
    await ep({ method: "GET", query: { r: hash(), i: "2", l: "en" } }, res);
    expect(res.statusCode).toBe(403);
  });
});

describe("filterFromBody sanitization", () => {
  it("keeps only known property types + coerces price", () => {
    expect(ep.filterFromBody({ property_types: ["land", "condo", "evil<script>"], max_price_usd: "500,000" }))
      .toEqual({ property_types: ["land", "condo"], max_price_usd: 500000 });
  });
  it("handles the urlencoded array key + non-numeric price", () => {
    expect(ep.filterFromBody({ "property_types[]": "house", max_price: "abc" })).toEqual({ property_types: ["house"] });
  });
  it("empty body → empty filter", () => {
    expect(ep.filterFromBody({})).toEqual({});
    expect(ep.filterFromBody(undefined)).toEqual({});
  });
});

describe("save / read round-trip via Resend last_name", () => {
  function mockResend(initialLast = "") {
    const store = [{ email: EMAIL, id: "c1", last_name: initialLast }];
    return {
      store,
      update: vi.fn(),
      client: {
        contacts: {
          list: vi.fn(async () => ({ data: { data: store } })),
          update: vi.fn(async (o) => { store[0].last_name = o.lastName; return {}; }),
        },
      },
    };
  }

  it("saveFilter writes the encoded filter to last_name", async () => {
    const m = mockResend();
    const out = await ep.saveFilter(hash(), { property_types: ["land"], max_price_usd: 500000 }, { resendImpl: m.client });
    expect(out.status).toBe("saved");
    expect(m.client.contacts.update).toHaveBeenCalledWith({ audienceId: "aud_test", email: EMAIL, lastName: "pulpo-filter:pt=land;mx=500000" });
  });

  it("saveFilter with an empty filter clears last_name", async () => {
    const m = mockResend("pulpo-filter:pt=land");
    await ep.saveFilter(hash(), {}, { resendImpl: m.client });
    expect(m.client.contacts.update).toHaveBeenCalledWith({ audienceId: "aud_test", email: EMAIL, lastName: "" });
  });

  it("readFilter decodes the stored last_name", async () => {
    const m = mockResend("pulpo-filter:pt=house,condo;mx=250000");
    const out = await ep.readFilter(hash(), { resendImpl: m.client });
    expect(out.pref).toEqual({ property_types: ["house", "condo"], max_price_usd: 250000 });
  });

  it("readFilter returns empty for a contact not in the audience", async () => {
    const m = mockResend();
    const out = await ep.readFilter("ffffffffffffffffffffffff", { resendImpl: m.client });
    expect(out.status).toBe("not_in_audience");
    expect(out.pref).toEqual({});
  });
});
