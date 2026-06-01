// Tests for api/admin/newsletter/template-version.js — the runtime
// reader that pulls TEMPLATE_VERSION + LAST_UPDATED from the Python
// source of truth (automation/newsletter/components/_common.py) and
// returns them as JSON so the admin widget can drop its hardcoded
// mirror.
//
// We don't run a Vercel function harness — just call the handler
// directly with mocked req/res + a stubbed `fs.readFileSync`.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";

let handler;

beforeEach(async () => {
  vi.resetModules();
  handler = (await import("../../api/admin/newsletter/template-version.js")).default;
});

afterEach(() => {
  vi.restoreAllMocks();
});

function mockRes() {
  const res = {
    statusCode: 200,
    headers: {},
    body: null,
    status(code) { this.statusCode = code; return this; },
    setHeader(k, v) { this.headers[k] = v; return this; },
    json(payload) { this.body = payload; return this; },
  };
  return res;
}

// ── method gate ─────────────────────────────────────────────────────


describe("method gate", () => {
  it("rejects POST with 405", async () => {
    const res = mockRes();
    await handler({ method: "POST" }, res);
    expect(res.statusCode).toBe(405);
    expect(res.body.error).toBe("method_not_allowed");
  });
});

// ── happy path ──────────────────────────────────────────────────────


describe("happy path", () => {
  it("returns the parsed version + lastUpdated for the canonical template", async () => {
    vi.spyOn(fs, "readFileSync").mockReturnValue(
      'TEMPLATE_VERSION = "newsletter-v4.4-2026-06-01"\n' +
      'LAST_UPDATED = "2026-06-01"\n'
    );
    const res = mockRes();
    await handler({ method: "GET" }, res);
    expect(res.statusCode).toBe(200);
    expect(res.body["pulpo-pro-general"]).toEqual({
      version: "v4.4",
      lastUpdated: "2026-06-01",
      fullVersion: "newsletter-v4.4-2026-06-01",
    });
  });

  it("stamps a 5-minute Cache-Control header on the response", async () => {
    vi.spyOn(fs, "readFileSync").mockReturnValue(
      'TEMPLATE_VERSION = "newsletter-v4.4-2026-06-01"\n' +
      'LAST_UPDATED = "2026-06-01"\n'
    );
    const res = mockRes();
    await handler({ method: "GET" }, res);
    expect(res.headers["Cache-Control"]).toMatch(/max-age=300/);
  });

  it("handles different version numbers correctly", async () => {
    vi.spyOn(fs, "readFileSync").mockReturnValue(
      'TEMPLATE_VERSION = "newsletter-v5.12-2027-01-15"\n' +
      'LAST_UPDATED = "2027-01-15"\n'
    );
    const res = mockRes();
    await handler({ method: "GET" }, res);
    expect(res.body["pulpo-pro-general"].version).toBe("v5.12");
    expect(res.body["pulpo-pro-general"].lastUpdated).toBe("2027-01-15");
  });

  it("returns BOTH templates when general + welcome constants are present", async () => {
    vi.spyOn(fs, "readFileSync").mockReturnValue(
      'TEMPLATE_VERSION = "newsletter-v4.4-2026-06-01"\n' +
      'LAST_UPDATED = "2026-06-01"\n' +
      'WELCOME_TEMPLATE_VERSION = "welcome-v1.0-2026-06-01"\n' +
      'WELCOME_LAST_UPDATED = "2026-06-01"\n'
    );
    const res = mockRes();
    await handler({ method: "GET" }, res);
    expect(res.statusCode).toBe(200);
    expect(res.body["pulpo-pro-general"]).toEqual({
      version: "v4.4",
      lastUpdated: "2026-06-01",
      fullVersion: "newsletter-v4.4-2026-06-01",
    });
    expect(res.body["pulpo-pro-welcome"]).toEqual({
      version: "v1.0",
      lastUpdated: "2026-06-01",
      fullVersion: "welcome-v1.0-2026-06-01",
    });
  });

  it("disambiguates TEMPLATE_VERSION from WELCOME_TEMPLATE_VERSION via line-start anchors", async () => {
    // The line-start `^` anchor + `m` flag in the regexes is what keeps
    // `WELCOME_TEMPLATE_VERSION = "welcome-v1.0-..."` from matching
    // the General's `TEMPLATE_VERSION` extractor (which would happen if
    // the regex were unanchored — "TEMPLATE_VERSION" is a substring of
    // "WELCOME_TEMPLATE_VERSION"). Putting WELCOME first in the fixture
    // exercises the ordering risk.
    vi.spyOn(fs, "readFileSync").mockReturnValue(
      'WELCOME_TEMPLATE_VERSION = "welcome-v1.0-2026-06-01"\n' +
      'WELCOME_LAST_UPDATED = "2026-06-01"\n' +
      'TEMPLATE_VERSION = "newsletter-v4.4-2026-06-01"\n' +
      'LAST_UPDATED = "2026-06-01"\n'
    );
    const res = mockRes();
    await handler({ method: "GET" }, res);
    expect(res.body["pulpo-pro-general"].fullVersion).toBe("newsletter-v4.4-2026-06-01");
    expect(res.body["pulpo-pro-welcome"].fullVersion).toBe("welcome-v1.0-2026-06-01");
  });
});

// ── degraded modes ──────────────────────────────────────────────────


describe("degraded modes", () => {
  it("returns 500 with diagnostic when the Python file is unreadable", async () => {
    vi.spyOn(fs, "readFileSync").mockImplementation(() => {
      const err = new Error("ENOENT");
      err.code = "ENOENT";
      throw err;
    });
    const res = mockRes();
    await handler({ method: "GET" }, res);
    expect(res.statusCode).toBe(500);
    expect(res.body.error).toBe("template_version_unavailable");
    expect(res.body.diagnostic).toContain("_common.py");
  });

  it("returns 500 when TEMPLATE_VERSION regex doesn't match", async () => {
    vi.spyOn(fs, "readFileSync").mockReturnValue(
      'SOMETHING_ELSE = "newsletter-v4.4-2026-06-01"\n' +
      'LAST_UPDATED = "2026-06-01"\n'
    );
    const res = mockRes();
    await handler({ method: "GET" }, res);
    expect(res.statusCode).toBe(500);
    expect(res.body.error).toBe("template_version_unparseable");
  });

  it("returns 500 when LAST_UPDATED regex doesn't match", async () => {
    vi.spyOn(fs, "readFileSync").mockReturnValue(
      'TEMPLATE_VERSION = "newsletter-v4.4-2026-06-01"\n' +
      'WRONG_KEY = "2026-06-01"\n'
    );
    const res = mockRes();
    await handler({ method: "GET" }, res);
    expect(res.statusCode).toBe(500);
    expect(res.body.error).toBe("template_version_unparseable");
  });

  it("returns 200 when General is present but Welcome constants are missing", async () => {
    // Welcome row degrades gracefully — its absence is not a 500.
    // The widget's card chrome falls back to "—" placeholders when a
    // template id is missing from the response. This lets future
    // templates land without forcing a downtime if their constants
    // haven't been wired yet.
    vi.spyOn(fs, "readFileSync").mockReturnValue(
      'TEMPLATE_VERSION = "newsletter-v4.4-2026-06-01"\n' +
      'LAST_UPDATED = "2026-06-01"\n'
    );
    const res = mockRes();
    await handler({ method: "GET" }, res);
    expect(res.statusCode).toBe(200);
    expect(res.body["pulpo-pro-general"]).toBeDefined();
    expect(res.body["pulpo-pro-welcome"]).toBeUndefined();
  });
});
