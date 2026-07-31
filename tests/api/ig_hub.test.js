// The bio-link hub lists live posts with their /go codes, degrades safely
// (missing queue / missing code / missing poster), escapes captions, and
// is wired above the /:slug catch-all.
import { describe, it, expect } from "vitest";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const require = createRequire(import.meta.url);
const REPO_ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), "../..");
const hub = require(path.join(REPO_ROOT, "api/ig-hub.js"));

const QUEUE = {
  items: [
    { day: 203, posted: true, posted_at: "2026-07-13T01:00:00Z",
      poster_path: "web/data/ig_assets/campaign/d03/slide1.png",
      attribution_code: "ig-d203-education", caption: "**Dejá de revisar 20 sitios.**\n\nx" },
    { day: 205, posted: true, posted_at: "2026-07-15T01:00:00Z",
      poster_path: "web/data/ig_assets/campaign/d05/slide1.png",
      attribution_code: "ig-d205-authority", caption: "**El país más seguro.**\n\ny" },
    { day: 99, posted: false, poster_path: "web/x.png", caption: "not posted" },   // filtered out
    { day: 210, posted: true, posted_at: "2026-07-20T01:00:00Z",
      poster_path: "web/p.png", caption: "**No code here.**" },                    // missing code
  ],
};

describe("activePosts", () => {
  it("keeps only posted items with a poster, newest first", () => {
    const p = hub.activePosts(QUEUE);
    expect(p.map((x) => x.day)).toEqual([210, 205, 203]); // 99 dropped, newest first
  });
  it("tolerates a null/garbage queue", () => {
    expect(hub.activePosts(null)).toEqual([]);
    expect(hub.activePosts({})).toEqual([]);
  });
});

describe("postHref", () => {
  it("links to the /go code when present", () => {
    expect(hub.postHref({ attribution_code: "ig-d203-education" })).toBe("/go/ig-d203-education");
  });
  it("falls back to home when no code (never a dead link)", () => {
    expect(hub.postHref({ day: 1 })).toBe("/");
  });
});

describe("hookOf", () => {
  it("extracts the bold hook", () => {
    expect(hub.hookOf("**The hook.**\n\nbody")).toBe("The hook.");
  });
  it("falls back to first line, then a default", () => {
    expect(hub.hookOf("just a line\nmore")).toBe("just a line");
    expect(hub.hookOf("")).toBe("Ver en Pulpo");
  });
});

describe("renderPage", () => {
  it("renders a card with a /go link per active post", () => {
    const html = hub.renderPage(hub.activePosts(QUEUE));
    expect(html.startsWith("<!DOCTYPE html>")).toBe(true);
    expect(html).toContain("/go/ig-d203-education");
    expect(html).toContain("/go/ig-d205-authority");
    expect(html).toContain("Sumate gratis");
  });
  it("renders a valid page with zero posts (empty drop)", () => {
    const html = hub.renderPage([]);
    expect(html).toContain("Muy pronto");
    expect(html).toContain("Sumate gratis"); // the CTA always survives
  });
  it("escapes caption text (no trust-render)", () => {
    const html = hub.renderPage([{ day: 1, posted: true, poster_path: "web/a.png",
      attribution_code: "ig-d1-scarcity", caption: "**<script>alert(1)</script>**" }]);
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain("&lt;script&gt;");
  });
});

describe("vercel wiring", () => {
  const cfg = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "vercel.json"), "utf8"));
  const sources = (cfg.rewrites || []).map((r) => r.source);
  it("routes /ig to the hub, above the catch-all", () => {
    expect((cfg.rewrites || []).find((r) => r.source === "/ig")?.destination).toBe("/api/ig-hub");
    const igIdx = sources.indexOf("/ig");
    const catchIdx = sources.findIndex((s) => s.startsWith("/:slug"));
    expect(igIdx).toBeGreaterThanOrEqual(0);
    expect(igIdx).toBeLessThan(catchIdx);
  });
});
