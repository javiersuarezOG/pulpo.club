// The v1 API's PII boundary, enforced at the source and at the bundle.
//
// Two catalog files exist and only one is safe to serve publicly:
//
//   web/data/ranked.json       carries broker_name / broker_phone /
//                              broker_email
//   web/data/ranked.list.json  the allowlisted projection with those
//                              fields stripped
//
// The website's loader legitimately falls back from the slim file to
// the full one when the slim file 404s. Copying that fallback into a
// public endpoint would mean a missing slim file silently starts
// publishing broker phone numbers — a quiet failure mode nobody would
// notice, which is the worst kind.
//
// This is a source-grep contract test, matching the convention already
// used by tests/api/email_type_contract.test.js and
// tests/api/vercel_security_headers.test.js. It cannot prove the
// handlers are correct; it proves this specific regression class is
// impossible to introduce by accident.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
// Every tree that serves the catalog publicly. api/mcp is here for the
// same reason api/v1 is: it reads the same files and answers anonymous
// callers, so the same boundary has to hold.
const SERVING_DIRS = ["api/v1", "api/mcp"];

function v1SourceFiles() {
  return SERVING_DIRS.flatMap((dir) => {
    const abs = path.join(repoRoot, dir);
    if (!fs.existsSync(abs)) return [];
    return fs
      .readdirSync(abs, { recursive: true, withFileTypes: true })
      .filter((e) => e.isFile() && /\.(ts|js|mjs)$/.test(e.name))
      .map((e) => path.join(e.parentPath ?? e.path, e.name));
  });
}

/**
 * Glob → RegExp, matching how Vercel treats excludeFiles patterns.
 *
 * Order matters and is easy to get wrong: substitute the wildcards
 * FIRST, via placeholders, then escape regex metacharacters. Escaping
 * dots first turns `ranked.*.json` into `ranked\.*\.json`, where the
 * `*` reads as "zero or more literal dots" — the assertion then quietly
 * passes on exactly the pattern it exists to catch. (It did, until this
 * was verified against a known-bad config.)
 */
function globToRegExp(glob) {
  const STAR2 = "\u0000";
  const STAR1 = "\u0001";
  const escaped = glob
    .replace(/\*\*/g, STAR2)
    .replace(/\*/g, STAR1)
    .replace(/[.+^${}()|[\]\\?]/g, "\\$&")
    .split(STAR2).join(".*")
    .split(STAR1).join("[^/]*");
  return new RegExp(`^${escaped}$`);
}

describe("public serving code never reaches for the PII catalog", () => {
  it("finds v1 handlers to check (guards against a vacuous pass)", () => {
    expect(v1SourceFiles().length).toBeGreaterThan(0);
  });

  it("references ranked.list.json and never ranked.json", () => {
    for (const file of v1SourceFiles()) {
      const src = fs.readFileSync(file, "utf8");
      // Strip comments: this file's own prose, and _catalog.ts's header
      // explaining the boundary, both legitimately name ranked.json.
      const code = src
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");

      const offending = code.match(/["'`][^"'`]*\branked\.json\b[^"'`]*["'`]/g);
      expect(
        offending,
        `${path.relative(repoRoot, file)} references ranked.json in code. The public ` +
          `API must read ranked.list.json only — ranked.json carries broker PII.`,
      ).toBeNull();
    }
  });

  it("has no fallback chain from the slim catalog to the full one", () => {
    const src = fs.readFileSync(path.join(repoRoot, "api", "v1", "_catalog.ts"), "utf8");
    const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    // Exactly one catalog filename is constructed, in catalogFilename().
    expect(code.match(/ranked\.list/g) ?? []).toHaveLength(2);
  });
});

describe("vercel.json keeps ranked.json out of every serving bundle", () => {
  const config = JSON.parse(fs.readFileSync(path.join(repoRoot, "vercel.json"), "utf8"));
  const v1Entries = Object.entries(config.functions ?? {}).filter(([k]) =>
    SERVING_DIRS.some((d) => k.startsWith(`${d}/`)),
  );

  it("configures every v1 function that reads the catalog", () => {
    expect(v1Entries.length).toBeGreaterThan(0);
  });

  for (const [name, cfg] of v1Entries) {
    describe(name, () => {
      const exclude = String(cfg.excludeFiles ?? "");
      const include = String(cfg.includeFiles ?? "");

      it("excludes the PII catalog from the deployed bundle", () => {
        // Defense in depth: even if a future handler regressed the
        // source rule above, the file would not be on disk to read.
        expect(exclude).toContain("web/data/ranked.json");
      });

      it("still ships the slim catalog it needs", () => {
        // Scoped to functions that actually READ the catalog. /ping is a
        // liveness probe that touches no data; demanding a 6 MB file in
        // its bundle would be cargo-culting the rule rather than
        // applying it.
        const entrypoint = path.join(repoRoot, name);
        const reads = fs.existsSync(entrypoint)
          && /loadCatalog|loadAdapted|_catalog/.test(fs.readFileSync(entrypoint, "utf8"));
        if (!reads) return;
        expect(include).toContain("web/data/ranked.list.json");
      });

      it("does not exclude the slim catalog by wildcard", () => {
        // `web/data/ranked.*.json` would match ranked.list.json and
        // 503 the endpoint in production while every test stayed green.
        for (const pattern of exclude.replace(/[{}]/g, "").split(",")) {
          const p = pattern.trim();
          if (!p) continue;
          expect(
            globToRegExp(p).test("web/data/ranked.list.json"),
            `excludeFiles pattern "${p}" also matches ranked.list.json, which would ` +
              `503 the endpoint in production while every test stayed green`,
          ).toBe(false);
        }
      });
    });
  }
});
