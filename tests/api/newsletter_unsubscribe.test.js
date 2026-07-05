// Unit tests for api/unsubscribe.js — runs under vitest (`npm test`).
// Covers HMAC token verify, RFC 8058 POST one-click, GET confirmation page,
// and parameter-validation edges. PostHog is silent no-op without the env.

import { describe, it, expect, beforeEach } from "vitest";

import handler, {
  expectedToken,
  verifyToken,
  hashEmail,
  recordResubscribe,
  recordUnsubscribe,
} from "../../api/unsubscribe.js";

function mockRes() {
  const res = {
    statusCode: 200,
    headers: {},
    body: null,
    status(code) { this.statusCode = code; return this; },
    setHeader(k, v) { this.headers[k] = v; return this; },
    json(payload) { this.body = payload; return this; },
    send(payload) { this.body = payload; return this; },
  };
  return res;
}

beforeEach(() => {
  process.env.PULPO_UNSUBSCRIBE_SECRET = "test-secret";
});

describe("hashEmail — cross-language contract with store.py email_hash", () => {
  // These golden values are computed by automation/newsletter/store.py's
  // email_hash() with the DEV_SALT ("pulpo-newsletter-dev-salt"):
  //   python3 -c "import hashlib; \
  //     print(hashlib.sha256('pulpo-newsletter-dev-salt:test@example.com'\
  //     .encode()).hexdigest()[:24])"  ->  402d0067182b8a07b852cf22
  // If JS drifts from Python, the unsubscribe/resubscribe link's r= hash
  // stops matching any Resend contact and BOTH flows silently no-op. Pin it.
  beforeEach(() => { delete process.env.PULPO_NEWSLETTER_SALT; });

  it("matches the Python salted 24-char hash for a known email", () => {
    expect(hashEmail("test@example.com")).toBe("402d0067182b8a07b852cf22");
  });

  it("lowercases + trims before hashing (parity with .strip().lower())", () => {
    expect(hashEmail("  TEST@Example.com  ")).toBe("402d0067182b8a07b852cf22");
  });

  it("honors PULPO_NEWSLETTER_SALT when set (same var Python reads)", () => {
    process.env.PULPO_NEWSLETTER_SALT = "prod-salt";
    // sha256("prod-salt:test@example.com")[:24]
    const crypto = require("crypto");
    const expected = crypto.createHash("sha256")
      .update("prod-salt:test@example.com").digest("hex").slice(0, 24);
    expect(hashEmail("test@example.com")).toBe(expected);
  });
});

describe("expectedToken", () => {
  it("is deterministic for the same (hash, issue)", () => {
    const a = expectedToken("abc", 1);
    const b = expectedToken("abc", 1);
    expect(a).toBe(b);
    expect(a.length).toBe(32);
  });

  it("changes when the issue or recipient changes", () => {
    expect(expectedToken("abc", 1)).not.toBe(expectedToken("abc", 2));
    expect(expectedToken("abc", 1)).not.toBe(expectedToken("xyz", 1));
  });

  it("returns null when secret is missing", () => {
    delete process.env.PULPO_UNSUBSCRIBE_SECRET;
    expect(expectedToken("abc", 1)).toBe(null);
  });
});

describe("verifyToken", () => {
  it("accepts a freshly-computed token", () => {
    const t = expectedToken("abc", 1);
    expect(verifyToken("abc", 1, t)).toBe(true);
  });

  it("rejects empty / wrong-length tokens", () => {
    expect(verifyToken("abc", 1, "")).toBe(false);
    expect(verifyToken("abc", 1, "shorter")).toBe(false);
  });

  it("rejects tokens for a different issue", () => {
    const t = expectedToken("abc", 1);
    expect(verifyToken("abc", 2, t)).toBe(false);
  });

  it("rejects when secret is missing", () => {
    delete process.env.PULPO_UNSUBSCRIBE_SECRET;
    expect(verifyToken("abc", 1, "x".repeat(32))).toBe(false);
  });
});

describe("handler", () => {
  it("405s on GET-ish methods other than GET/POST", async () => {
    const req = { method: "DELETE", query: {}, headers: {} };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(405);
    expect(res.body.error).toBe("method_not_allowed");
  });

  it("400s when params are missing", async () => {
    const req = { method: "GET", query: { r: "abc" }, headers: {} };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toBe("invalid_link");
  });

  it("400s on bad token", async () => {
    const req = {
      method: "GET",
      query: { r: "abc", i: "1", t: "x".repeat(32) },
      headers: {},
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toBe("invalid_link");
  });

  it("200s + renders HTML on valid GET", async () => {
    const t = expectedToken("abc", 1);
    const req = {
      method: "GET",
      query: { r: "abc", i: "1", t },
      headers: {},
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(200);
    expect(res.headers["Content-Type"]).toContain("text/html");
    expect(res.body).toContain("You're unsubscribed.");
  });

  it("defaults to the FREE edition (upsell copy, no PRO badge) when e is absent", async () => {
    const t = expectedToken("abc", 1);
    const req = { method: "GET", query: { r: "abc", i: "1", t }, headers: {} };
    const res = mockRes();
    await handler(req, res);
    expect(res.body).toContain("You're unsubscribed.");
    expect(res.body).toContain("The full shortlist lives in Pulpo Pro.");
    // No gold PRO chip rendered on the free masthead (the .pro-pill CSS
    // class lives in the shared <style> block; assert on the element).
    expect(res.body).not.toContain('<span class="pro-pill">PRO</span>');
  });

  it("renders the PRO retention page (no upsell) for e=pro", async () => {
    const t = expectedToken("abc", 1);
    const req = { method: "GET", query: { r: "abc", i: "1", t, e: "pro" }, headers: {} };
    const res = mockRes();
    await handler(req, res);
    expect(res.body).toContain("You're off the weekly.");
    expect(res.body).toContain("membership</strong> is still active");
    expect(res.body).toContain('<span class="pro-pill">PRO</span>'); // gold PRO badge present
    // Pro page is retention, not upsell — it must NOT pitch Pro.
    expect(res.body).not.toContain("The full shortlist lives in Pulpo Pro.");
  });

  it("renders Spanish copy for l=es (free + pro)", async () => {
    const t = expectedToken("abc", 1);
    const freeRes = mockRes();
    await handler({ method: "GET", query: { r: "abc", i: "1", t, l: "es" }, headers: {} }, freeRes);
    expect(freeRes.body).toContain("Cancelaste tu suscripción.");
    expect(freeRes.body).toContain('lang="es"');

    const proRes = mockRes();
    await handler({ method: "GET", query: { r: "abc", i: "1", t, e: "pro", l: "es" }, headers: {} }, proRes);
    expect(proRes.body).toContain("Saliste del resumen semanal.");
  });

  it("falls back to free/en on a garbage e/l (cosmetic params, never trusted)", async () => {
    const t = expectedToken("abc", 1);
    const req = { method: "GET", query: { r: "abc", i: "1", t, e: "../etc", l: "fr" }, headers: {} };
    const res = mockRes();
    await handler(req, res);
    expect(res.body).toContain("You're unsubscribed.");
    expect(res.body).toContain('lang="en"');
  });

  it("renders the resubscribe confirmation (free) on action=resub", async () => {
    const t = expectedToken("abc", 1);
    const req = { method: "GET", query: { r: "abc", i: "1", t, action: "resub" }, headers: {} };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(200);
    expect(res.headers["Content-Type"]).toContain("text/html");
    expect(res.body).toContain("You're back on the list.");
    // Not the unsubscribe confirmation.
    expect(res.body).not.toContain("You're unsubscribed.");
  });

  it("renders the resubscribe confirmation (pro) on action=resub&e=pro", async () => {
    const t = expectedToken("abc", 1);
    const req = { method: "GET", query: { r: "abc", i: "1", t, e: "pro", action: "resub" }, headers: {} };
    const res = mockRes();
    await handler(req, res);
    expect(res.body).toContain("You're back on the weekly.");
    expect(res.body).toContain('<span class="pro-pill">PRO</span>');
  });

  it("resub page renders Spanish copy for l=es", async () => {
    const t = expectedToken("abc", 1);
    const req = { method: "GET", query: { r: "abc", i: "1", t, l: "es", action: "resub" }, headers: {} };
    const res = mockRes();
    await handler(req, res);
    expect(res.body).toContain("Estás de vuelta en la lista.");
  });

  it("the unsubscribe page's Resubscribe link carries the same token + action=resub", async () => {
    const t = expectedToken("abc", 1);
    const req = { method: "GET", query: { r: "abc", i: "1", t }, headers: {} };
    const res = mockRes();
    await handler(req, res);
    // The free ghost CTA now round-trips through the token endpoint, not `/`.
    expect(res.body).toContain(`action=resub`);
    expect(res.body).toContain(`r=abc&i=1&t=${t}`);
  });

  it("still 400s on a bad token even with action=resub (no forgery path)", async () => {
    const req = {
      method: "GET",
      query: { r: "abc", i: "1", t: "x".repeat(32), action: "resub" },
      headers: {},
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toBe("invalid_link");
  });

  it("200s with JSON on valid POST (RFC 8058 one-click)", async () => {
    const t = expectedToken("xyz", 7);
    const req = {
      method: "POST",
      query: { r: "xyz", i: "7", t },
      headers: {},
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(200);
    expect(res.body.ok).toBe(true);
  });
});

describe("recordResubscribe — welcome-back dispatch", () => {
  const EMAIL = "resub@example.com";

  function fakeResend({ unsubscribed }) {
    return {
      contacts: {
        list: async () => ({ data: [{ id: "c1", email: EMAIL, unsubscribed }] }),
        update: async () => ({ data: { id: "c1" } }),
      },
    };
  }

  function recordingFetch(calls) {
    return async (url, opts) => {
      calls.push({ url, body: JSON.parse(opts.body) });
      return { status: 200, json: async () => ({ status: "sent", dry_run: true }) };
    };
  }

  beforeEach(() => {
    process.env.RESEND_AUDIENCE_ID = "aud_test";
    process.env.RESEND_API_KEY = "re_test";
    process.env.PULPO_INTERNAL_TOKEN = "internal_test";
  });

  it("fires free_welcome_back on a genuine free resubscribe, carrying email + locale", async () => {
    const calls = [];
    const out = await recordResubscribe(hashEmail(EMAIL), 3, {
      edition: "free",
      locale: "es",
      fetchImpl: recordingFetch(calls),
      resendImpl: fakeResend({ unsubscribed: true }),
    });
    expect(out.resend_status).toBe("updated");
    expect(out.was_unsubscribed).toBe(true);
    expect(calls.length).toBe(1);
    expect(calls[0].body.variant).toBe("free_welcome_back");
    expect(calls[0].body.email).toBe(EMAIL);
    expect(calls[0].body.locale).toBe("es");
  });

  it("does NOT fire when the contact was already subscribed (repeat click)", async () => {
    const calls = [];
    const out = await recordResubscribe(hashEmail(EMAIL), 3, {
      edition: "free",
      fetchImpl: recordingFetch(calls),
      resendImpl: fakeResend({ unsubscribed: false }),
    });
    expect(out.resend_status).toBe("updated");
    expect(out.was_unsubscribed).toBe(false);
    expect(calls.length).toBe(0);
  });

  it("fires the PRO welcome-back (welcome-send, variant=welcome_back) for a Pro edition resubscribe", async () => {
    const calls = [];
    const out = await recordResubscribe(hashEmail(EMAIL), 3, {
      edition: "pro",
      locale: "es",
      fetchImpl: recordingFetch(calls),
      resendImpl: fakeResend({ unsubscribed: true }),
    });
    expect(out.resend_status).toBe("updated");
    expect(calls.length).toBe(1);
    // Pro routes to the Pro dispatcher, NOT the free one.
    expect(calls[0].url).toContain("/api/internal/welcome-send");
    expect(calls[0].url).not.toContain("free-welcome-send");
    expect(calls[0].body.variant).toBe("welcome_back");
    expect(calls[0].body.source).toBe("unsubscribe_page_resub");
    expect(calls[0].body.locale).toBe("es");
    // No subscription_id → can't collide with the Stripe re-acquisition dedup.
    expect(calls[0].body.subscription_id).toBeUndefined();
  });

  it("does NOT fire the Pro welcome-back when the contact was already subscribed", async () => {
    const calls = [];
    const out = await recordResubscribe(hashEmail(EMAIL), 3, {
      edition: "pro",
      fetchImpl: recordingFetch(calls),
      resendImpl: fakeResend({ unsubscribed: false }),
    });
    expect(out.resend_status).toBe("updated");
    expect(out.was_unsubscribed).toBe(false);
    expect(calls.length).toBe(0);
  });

  it("still resubscribes even if the welcome dispatch throws", async () => {
    const out = await recordResubscribe(hashEmail(EMAIL), 3, {
      edition: "free",
      fetchImpl: async () => { throw new Error("network down"); },
      resendImpl: fakeResend({ unsubscribed: true }),
    });
    expect(out.resend_status).toBe("updated");
    // fireFreeWelcome catches its own fetch errors → returns fired:false.
    expect(out.welcome.fired).toBe(false);
  });
});

describe("recordUnsubscribe — Resend mirror retry (P0-2)", () => {
  const EMAIL = "unsub@example.com";

  beforeEach(() => {
    process.env.RESEND_AUDIENCE_ID = "aud_test";
    process.env.RESEND_API_KEY = "re_test";
    delete process.env.PULPO_NEWSLETTER_SALT; // dev-salt parity for hashEmail
  });

  function fakeResend({ updateBehaviour }) {
    let updateCalls = 0;
    const impl = {
      contacts: {
        list: async () => ({ data: [{ id: "c1", email: EMAIL, unsubscribed: false }] }),
        update: async () => {
          updateCalls += 1;
          return updateBehaviour(updateCalls);
        },
      },
    };
    Object.defineProperty(impl, "updateCalls", { get: () => updateCalls });
    return impl;
  }

  it("retries a transient update failure and reports success", async () => {
    // Fail the first two attempts, succeed on the third.
    const resend = fakeResend({
      updateBehaviour: (n) => {
        if (n < 3) throw new Error("503 upstream");
        return { data: { id: "c1" } };
      },
    });
    const out = await recordUnsubscribe(hashEmail(EMAIL), 7, { resendImpl: resend });
    expect(out.resend_status).toBe("updated");
    expect(out.attempts).toBe(3);
    expect(resend.updateCalls).toBe(3);
  });

  it("returns update_failed (not a false success) after exhausting retries", async () => {
    const resend = fakeResend({
      updateBehaviour: () => { throw new Error("503 upstream"); },
    });
    const out = await recordUnsubscribe(hashEmail(EMAIL), 7, { resendImpl: resend });
    expect(out.resend_status).toBe("update_failed");
    expect(resend.updateCalls).toBe(3); // bounded, not infinite
  });
});
