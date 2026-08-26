// Contract tests for GET /api/v1/ping — the module-chain spike.
//
// The interesting assertions here are not "does it return 200". They
// are the two import-interop facts the rest of the API layer is built
// on, which this handler exercises by construction:
//
//   * a TypeScript handler under api/ can import ESM TypeScript from
//     shared/ (the `version` assertion — the value comes from
//     shared/version.ts, so a broken chain fails to import at all)
//   * the same handler can import the CommonJS helpers under api/
//     (the rate-limit assertions — send429/ipFromRequest/makeRateLimiter
//     all come from api/_rate_limit.js)
//
// Local green here is necessary but not sufficient: vitest resolves
// modules with Vite, Vercel resolves them with esbuild. The preview
// curl in the PR body is what actually settles the deploy question.

import { describe, expect, it } from "vitest";
import handler from "../../api/v1/ping.ts";
import { API_VERSION } from "../../shared/version.ts";

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

function mockReq(overrides = {}) {
  return {
    method: "GET",
    headers: { "x-forwarded-for": "203.0.113.9" },
    ...overrides,
  };
}

describe("GET /api/v1/ping", () => {
  it("returns ok with the shared contract version", () => {
    const res = mockRes();
    handler(mockReq(), res);

    expect(res.statusCode).toBe(200);
    expect(res.body.ok).toBe(true);
    // Sourced from shared/version.ts, not a literal — this is the
    // cross-tree import proof.
    expect(res.body.version).toBe(API_VERSION);
    expect(res.body.version).toBe("v1");
    expect(() => new Date(res.body.now).toISOString()).not.toThrow();
  });

  it("is never cached — a cached liveness probe proves nothing", () => {
    const res = mockRes();
    handler(mockReq(), res);
    expect(res.headers["Cache-Control"]).toBe("no-store");
  });

  it("rejects non-GET with 405 and an Allow header", () => {
    for (const method of ["POST", "PUT", "DELETE"]) {
      const res = mockRes();
      handler(mockReq({ method }), res);
      expect(res.statusCode).toBe(405);
      expect(res.body).toEqual({ error: "method_not_allowed" });
      expect(res.headers.Allow).toBe("GET");
    }
  });

  it("rate-limits a single IP and answers with the house 429 shape", () => {
    // Distinct IP so this test cannot be perturbed by the other cases
    // sharing the module-level limiter instance.
    const ip = "198.51.100.77";
    let last = null;

    // The limiter allows 120/min; drive past it.
    for (let i = 0; i < 130; i++) {
      last = mockRes();
      handler(mockReq({ headers: { "x-forwarded-for": ip } }), last);
    }

    expect(last.statusCode).toBe(429);
    expect(last.body.error).toBe("rate_limited");
    expect(last.body.limiter).toBe("v1_ping");
    expect(Number(last.headers["Retry-After"])).toBeGreaterThan(0);
  });
});
