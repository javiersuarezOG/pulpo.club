// Unit tests for api/_rate_limit.js. Pins the contract that downstream
// endpoints (saves, geo, future callers) rely on:
//
//   - first MAX_ATTEMPTS hits in a window allow through
//   - the (MAX_ATTEMPTS + 1)th in the window 429s with a Retry-After
//   - hits past the window reset the bucket
//   - distinct keys don't share buckets
//   - bad config raises at construction time (fail-fast, not silent)
//
// Runs under vitest (`npm test`). No fake clock — windows are sized so
// real-time progression doesn't matter for assertions.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  makeRateLimiter,
  ipFromRequest,
  send429,
} from "../../api/_rate_limit.js";

describe("makeRateLimiter", () => {
  describe("config validation", () => {
    it("throws on non-positive windowMs", () => {
      expect(() => makeRateLimiter({ windowMs: 0, maxAttempts: 5 }))
        .toThrow(/windowMs must be positive/);
      expect(() => makeRateLimiter({ windowMs: -1, maxAttempts: 5 }))
        .toThrow(/windowMs must be positive/);
    });

    it("throws on non-integer or non-positive maxAttempts", () => {
      expect(() => makeRateLimiter({ windowMs: 1000, maxAttempts: 0 }))
        .toThrow(/maxAttempts must be a positive integer/);
      expect(() => makeRateLimiter({ windowMs: 1000, maxAttempts: 1.5 }))
        .toThrow(/maxAttempts must be a positive integer/);
    });
  });

  describe("allow / deny semantics", () => {
    it("allows the first maxAttempts hits within the window", () => {
      const rl = makeRateLimiter({ windowMs: 60_000, maxAttempts: 3 });
      for (let i = 0; i < 3; i++) {
        const r = rl.hit("user-a");
        expect(r.allowed).toBe(true);
        expect(r.remaining).toBe(3 - 1 - i);
      }
    });

    it("denies the (maxAttempts + 1)th hit with a retryAfterMs", () => {
      const rl = makeRateLimiter({ windowMs: 60_000, maxAttempts: 2 });
      rl.hit("user-a");
      rl.hit("user-a");
      const r = rl.hit("user-a");
      expect(r.allowed).toBe(false);
      expect(r.remaining).toBe(0);
      expect(r.retryAfterMs).toBeGreaterThan(0);
      // Within one window
      expect(r.retryAfterMs).toBeLessThanOrEqual(60_000);
    });

    it("isolates keys — exhausting user-a doesn't block user-b", () => {
      const rl = makeRateLimiter({ windowMs: 60_000, maxAttempts: 1 });
      expect(rl.hit("user-a").allowed).toBe(true);
      expect(rl.hit("user-a").allowed).toBe(false);
      expect(rl.hit("user-b").allowed).toBe(true);  // unaffected
    });

    it("buckets null / undefined keys together under 'unknown'", () => {
      const rl = makeRateLimiter({ windowMs: 60_000, maxAttempts: 1 });
      expect(rl.hit(null).allowed).toBe(true);
      expect(rl.hit(undefined).allowed).toBe(false);
    });
  });

  describe("window expiration", () => {
    beforeEach(() => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-05-19T00:00:00Z"));
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("fresh requests beyond the window roll the bucket forward", () => {
      const rl = makeRateLimiter({ windowMs: 1000, maxAttempts: 2 });
      expect(rl.hit("k").allowed).toBe(true);
      expect(rl.hit("k").allowed).toBe(true);
      expect(rl.hit("k").allowed).toBe(false);
      // Advance past the window
      vi.advanceTimersByTime(1500);
      expect(rl.hit("k").allowed).toBe(true);
      expect(rl.hit("k").allowed).toBe(true);
    });
  });

  describe("reset()", () => {
    it("wipes all keys for the limiter instance (test-only escape hatch)", () => {
      const rl = makeRateLimiter({ windowMs: 60_000, maxAttempts: 1 });
      rl.hit("user-a");
      expect(rl.hit("user-a").allowed).toBe(false);
      rl.reset();
      expect(rl.hit("user-a").allowed).toBe(true);
    });
  });
});

describe("ipFromRequest", () => {
  it("returns the first hop of x-forwarded-for", () => {
    const req = { headers: { "x-forwarded-for": "1.2.3.4, 10.0.0.1, 10.0.0.2" } };
    expect(ipFromRequest(req)).toBe("1.2.3.4");
  });

  it("trims whitespace from the first hop", () => {
    const req = { headers: { "x-forwarded-for": "  1.2.3.4  , 10.0.0.1" } };
    expect(ipFromRequest(req)).toBe("1.2.3.4");
  });

  it("falls back to socket.remoteAddress when XFF is missing", () => {
    const req = { headers: {}, socket: { remoteAddress: "5.6.7.8" } };
    expect(ipFromRequest(req)).toBe("5.6.7.8");
  });

  it("buckets unknown sources under a shared 'unknown' key", () => {
    expect(ipFromRequest({ headers: {} })).toBe("unknown");
    expect(ipFromRequest({})).toBe("unknown");
    expect(ipFromRequest(null)).toBe("unknown");
  });

  it("does NOT honor a missing-but-present XFF header", () => {
    // Empty string from a misconfigured proxy should fall through to socket
    const req = { headers: { "x-forwarded-for": "" }, socket: { remoteAddress: "9.9.9.9" } };
    expect(ipFromRequest(req)).toBe("9.9.9.9");
  });
});

describe("send429", () => {
  function buildRes() {
    const res = {
      statusCode: null,
      headers: {},
      body: null,
      setHeader(k, v) { this.headers[k] = v; },
      status(code) { this.statusCode = code; return this; },
      json(b) { this.body = b; return this; },
    };
    return res;
  }

  it("returns 429 with Retry-After in seconds (rounded up, floor 1)", () => {
    const res = buildRes();
    send429(res, { allowed: false, retryAfterMs: 1500 }, "saves");
    expect(res.statusCode).toBe(429);
    expect(res.headers["Retry-After"]).toBe("2");
    expect(res.body).toEqual({
      error: "rate_limited",
      retry_after_s: 2,
      limiter: "saves",
    });
  });

  it("clamps Retry-After to a minimum of 1 second", () => {
    const res = buildRes();
    send429(res, { allowed: false, retryAfterMs: 50 }, "geo");
    expect(res.headers["Retry-After"]).toBe("1");
    expect(res.body.retry_after_s).toBe(1);
  });
});
