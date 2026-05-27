import { afterEach, describe, expect, it, vi } from "vitest";
import handler from "../../api/csp-report.js";

function mockRes() {
  return {
    statusCode: 200,
    headers: {},
    body: null,
    setHeader(k, v) { this.headers[k] = v; return this; },
    status(code) { this.statusCode = code; return this; },
    json(payload) { this.body = payload; return this; },
  };
}

afterEach(() => {
  handler.__testing__.setPosthogClient({
    capture: () => {},
    flush: async () => {},
  });
  vi.restoreAllMocks();
});

describe("normalizeReport", () => {
  const { normalizeReport } = handler.__testing__;

  it("normalizes legacy application/csp-report payloads", () => {
    const out = normalizeReport({
      "csp-report": {
        "blocked-uri": "https://challenges.cloudflare.com/turnstile/v0/api.js",
        "violated-directive": "script-src",
        "document-uri": "https://pulpo.club/account",
        "original-policy": "default-src 'self'",
        "source-file": "https://pulpo.club/build/index.js",
        "line-number": 17,
      },
    });
    expect(out).toMatchObject({
      blocked_uri: "https://challenges.cloudflare.com/turnstile/v0/api.js",
      violated_directive: "script-src",
      document_uri: "https://pulpo.club/account",
      line_number: 17,
    });
  });

  it("normalizes Reporting API array payloads", () => {
    const out = normalizeReport([{
      type: "csp-violation",
      body: {
        blockedURL: "https://example.invalid/script.js",
        effectiveDirective: "script-src",
        documentURL: "https://pulpo.club/start",
        originalPolicy: "default-src 'self'",
        sourceFile: "https://pulpo.club/build/start.js",
        lineNumber: 42,
      },
    }]);
    expect(out).toMatchObject({
      blocked_uri: "https://example.invalid/script.js",
      violated_directive: "script-src",
      document_uri: "https://pulpo.club/start",
      line_number: 42,
    });
  });

  it("returns null for missing/invalid shapes", () => {
    expect(normalizeReport(null)).toBeNull();
    expect(normalizeReport({})).toBeNull();
    expect(normalizeReport({ body: {} })).toBeNull();
  });
});

describe("handler", () => {
  it("405s on non-POST", async () => {
    const res = mockRes();
    await handler({ method: "GET", headers: {} }, res);
    expect(res.statusCode).toBe(405);
    expect(res.body.error).toBe("method_not_allowed");
  });

  it("400s on invalid report bodies", async () => {
    const res = mockRes();
    await handler({
      method: "POST",
      headers: { "x-forwarded-for": "203.0.113.10" },
      body: {},
    }, res);
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toBe("invalid_report");
  });

  it("captures valid reports to PostHog", async () => {
    const capture = vi.fn();
    const flush = vi.fn().mockResolvedValue(undefined);
    handler.__testing__.setPosthogClient({ capture, flush });
    const res = mockRes();
    await handler({
      method: "POST",
      headers: { "x-forwarded-for": "203.0.113.11" },
      body: {
        "csp-report": {
          "blocked-uri": "https://challenges.cloudflare.com",
          "violated-directive": "script-src",
          "document-uri": "https://pulpo.club/account",
        },
      },
    }, res);

    expect(res.statusCode).toBe(200);
    expect(res.body.ok).toBe(true);
    expect(capture).toHaveBeenCalledWith(
      "server:csp-report",
      "csp.violation",
      expect.objectContaining({
        blocked_uri: "https://challenges.cloudflare.com",
        violated_directive: "script-src",
      }),
    );
    expect(flush).toHaveBeenCalledTimes(1);
  });

  it("rate-limits the 61st request per IP", async () => {
    const ip = "203.0.113.61";
    const validBody = {
      "csp-report": {
        "blocked-uri": "https://example.invalid",
        "violated-directive": "script-src",
        "document-uri": "https://pulpo.club/account",
      },
    };

    for (let i = 0; i < 60; i += 1) {
      const res = mockRes();
      await handler({ method: "POST", headers: { "x-forwarded-for": ip }, body: validBody }, res);
      expect(res.statusCode).toBe(200);
    }

    const res = mockRes();
    await handler({ method: "POST", headers: { "x-forwarded-for": ip }, body: validBody }, res);
    expect(res.statusCode).toBe(429);
    expect(res.body.error).toBe("rate_limited");
    expect(res.body.limiter).toBe("csp_report");
  });
});
