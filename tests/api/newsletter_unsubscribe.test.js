// Unit tests for api/unsubscribe.js — runs under vitest (`npm test`).
// Covers HMAC token verify, RFC 8058 POST one-click, GET confirmation page,
// and parameter-validation edges. PostHog is silent no-op without the env.

import { describe, it, expect, beforeEach } from "vitest";

import handler, { expectedToken, verifyToken } from "../../api/unsubscribe.js";

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
