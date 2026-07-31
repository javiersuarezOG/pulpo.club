// Unit tests for the per-post IG attribution redirector (api/go/[code].js).
// Pure logic (parseCode/buildDestination) + a handler smoke test asserting
// the 302 + first-touch UTMs that carry signup attribution back to a post.
import { describe, it, expect } from "vitest";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const require = createRequire(import.meta.url);
const REPO_ROOT = path.resolve(
  path.dirname(url.fileURLToPath(import.meta.url)),
  "../..",
);
const router = require(path.join(REPO_ROOT, "api/go/[code].js"));
const { parseCode, buildDestination } = router;

describe("parseCode", () => {
  it("parses day + category, defaulting tier to free", () => {
    expect(parseCode("ig-d217-scarcity")).toEqual({
      code: "ig-d217-scarcity",
      day: 217,
      category: "scarcity",
      tier: "free",
    });
  });

  it("parses an explicit pro tier and keeps it in the code", () => {
    expect(parseCode("ig-d5-investment-pro")).toEqual({
      code: "ig-d5-investment-pro",
      day: 5,
      category: "investment",
      tier: "pro",
    });
  });

  it("accepts underscored categories (social_proof)", () => {
    expect(parseCode("ig-d1-social_proof")?.category).toBe("social_proof");
  });

  it("is case-insensitive", () => {
    expect(parseCode("IG-D217-SCARCITY")?.category).toBe("scarcity");
  });

  it("rejects an unknown category (no arbitrary utm_term injection)", () => {
    expect(parseCode("ig-d217-clickbait")).toBeNull();
  });

  it("rejects malformed codes", () => {
    for (const bad of ["", "ig-217-scarcity", "d217-scarcity", "ig-dXX-scarcity", "../etc", null]) {
      expect(parseCode(bad)).toBeNull();
    }
  });
});

describe("buildDestination", () => {
  it("free tier lands on the homepage with first-touch UTMs", () => {
    const dest = buildDestination(parseCode("ig-d217-scarcity"));
    const u = new URL(dest, "https://pulpo.club");
    expect(u.pathname).toBe("/");
    expect(u.searchParams.get("utm_source")).toBe("instagram");
    expect(u.searchParams.get("utm_medium")).toBe("social");
    expect(u.searchParams.get("utm_content")).toBe("ig-d217-scarcity"); // the post
    expect(u.searchParams.get("utm_term")).toBe("scarcity"); // the lever
  });

  it("pro tier lands on /start", () => {
    const u = new URL(buildDestination(parseCode("ig-d5-investment-pro")), "https://pulpo.club");
    expect(u.pathname).toBe("/start");
    expect(u.searchParams.get("utm_content")).toBe("ig-d5-investment-pro");
  });

  it("an unknown code still redirects same-origin (never open-redirect)", () => {
    const u = new URL(buildDestination(null), "https://pulpo.club");
    expect(u.pathname).toBe("/");
    expect(u.searchParams.get("utm_source")).toBe("instagram");
  });
});

describe("handler", () => {
  function mockRes() {
    return {
      statusCode: 0,
      headers: {},
      body: "",
      setHeader(k, v) { this.headers[k.toLowerCase()] = v; },
      end(b) { this.body = b || ""; },
    };
  }

  it("302s to the stamped destination for a valid code", async () => {
    const res = mockRes();
    await router({ query: { code: "ig-d217-scarcity" }, url: "/go/ig-d217-scarcity" }, res);
    expect(res.statusCode).toBe(302);
    const loc = res.headers["location"];
    expect(loc.startsWith("/?")).toBe(true);
    expect(loc).toContain("utm_content=ig-d217-scarcity");
    expect(res.headers["cache-control"]).toBe("no-store");
  });

  it("falls back to the URL param when req.query is empty", async () => {
    const res = mockRes();
    await router({ query: {}, url: "/go/ig-d5-investment-pro" }, res);
    expect(res.statusCode).toBe(302);
    expect(res.headers["location"].startsWith("/start?")).toBe(true);
  });

  it("degrades a garbage code to a same-origin redirect (no crash)", async () => {
    const res = mockRes();
    await router({ query: { code: "../../etc/passwd" }, url: "/go/x" }, res);
    expect(res.statusCode).toBe(302);
    expect(res.headers["location"].startsWith("/?")).toBe(true);
  });
});

describe("vercel.json wiring", () => {
  const config = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "vercel.json"), "utf8"));
  const sources = (config.rewrites || []).map((r) => r.source);

  it("routes /go/:code to the function", () => {
    const rule = (config.rewrites || []).find((r) => r.source === "/go/:code");
    expect(rule?.destination).toBe("/api/go/:code");
  });

  it("declares /go/:code ABOVE the /:slug catch-all (or it 404s)", () => {
    const goIdx = sources.indexOf("/go/:code");
    const catchIdx = sources.findIndex((s) => s.startsWith("/:slug"));
    expect(goIdx).toBeGreaterThanOrEqual(0);
    expect(goIdx).toBeLessThan(catchIdx);
  });
});
