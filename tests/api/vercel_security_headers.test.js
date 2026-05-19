// Pins the security headers configured in vercel.json. A future edit
// that removes the catch-all header block (or downgrades one of the
// values) fails this test instead of silently shipping. The header
// values come straight from the OWASP Secure Headers project + the
// audit recommendations.
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const REPO_ROOT = path.resolve(
  path.dirname(url.fileURLToPath(import.meta.url)),
  "../..",
);

const config = JSON.parse(
  fs.readFileSync(path.join(REPO_ROOT, "vercel.json"), "utf8"),
);

function findHeaderRule(source) {
  return (config.headers || []).find((r) => r.source === source);
}

function headerValue(rule, name) {
  const entry = (rule.headers || []).find((h) => h.key === name);
  return entry ? entry.value : null;
}

describe("vercel.json security headers", () => {
  const catchAll = findHeaderRule("/(.*)");

  it("declares a catch-all header rule covering every route", () => {
    expect(catchAll).toBeTruthy();
  });

  it("enforces HSTS with includeSubDomains + preload (>= 1 year)", () => {
    const v = headerValue(catchAll, "Strict-Transport-Security");
    expect(v).toBeTruthy();
    // Standard preload-list minimum is 31536000 (1 year)
    const m = /max-age=(\d+)/.exec(v);
    expect(m).toBeTruthy();
    expect(Number(m[1])).toBeGreaterThanOrEqual(31536000);
    expect(v).toMatch(/includeSubDomains/);
    expect(v).toMatch(/preload/);
  });

  it("sets X-Content-Type-Options: nosniff", () => {
    expect(headerValue(catchAll, "X-Content-Type-Options")).toBe("nosniff");
  });

  it("sets X-Frame-Options to deny cross-origin framing", () => {
    const v = headerValue(catchAll, "X-Frame-Options");
    expect(["DENY", "SAMEORIGIN"]).toContain(v);
  });

  it("sets Referrer-Policy to a privacy-preserving value", () => {
    const v = headerValue(catchAll, "Referrer-Policy");
    // Either of these is acceptable per OWASP; the stricter
    // "no-referrer" is also fine if someone ever tightens this.
    expect([
      "strict-origin-when-cross-origin",
      "same-origin",
      "no-referrer",
    ]).toContain(v);
  });

  it("disables unused powerful browser APIs via Permissions-Policy", () => {
    const v = headerValue(catchAll, "Permissions-Policy");
    expect(v).toBeTruthy();
    // We don't currently use camera/microphone/geolocation; if a future
    // feature needs one of these the engineer must consciously remove
    // it from this block AND update the test below.
    expect(v).toMatch(/camera=\(\)/);
    expect(v).toMatch(/microphone=\(\)/);
    expect(v).toMatch(/geolocation=\(\)/);
  });
});
