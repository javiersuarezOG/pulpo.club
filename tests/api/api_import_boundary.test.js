// THE api/ BOUNDARY RULE — what took production down, encoded as a test.
//
// INCIDENT (2026-08-25 → 27). Every /api/v1/* and /api/mcp endpoint
// returned 500 FUNCTION_INVOCATION_FAILED while CI was green and the
// website was fine.
//
// Established by deploying probe functions to a preview and bisecting:
//
//   CommonJS entrypoint            -> outside api/     200
//   TS entrypoint -> .js inside api/ (self-contained)  200
//   TS entrypoint -> .ts inside api/                   200
//   TS entrypoint -> shared/*.ts   (OUTSIDE)           500
//   TS entrypoint -> plain .js     (OUTSIDE)           500
//   TS entrypoint -> .js inside api/ -> OUTSIDE        500   <-- transitive
//
// Vercel compiles TypeScript functions only for files inside api/, and
// the restriction is TRANSITIVE: nothing in a .ts function's dependency
// graph may reach outside api/, at any depth. A CommonJS entrypoint has
// no such limit, because its requires are resolved by the file tracer
// rather than the compiler.
//
// Two earlier theories were wrong and are recorded so nobody re-tries
// them: it is not a module-format problem (a no-import .ts function
// works fine either way), and includeFiles does not help (the files
// were never missing, they were uncompiled).
//
// THE RULE THIS ENFORCES: serverless entrypoints that need the shared
// core are CommonJS .js, reaching it through api/_core.js.
//
// A behavioural test cannot catch this class — specs import the source
// through Vite, which resolves everything happily. The failure exists
// only in Vercel's emitted bundle, which is exactly why it shipped
// green the first time. So this asserts the shape instead.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const apiDir = path.join(repoRoot, "api");

function walk(dir) {
  return fs.readdirSync(dir, { recursive: true, withFileTypes: true })
    .filter((e) => e.isFile())
    .map((e) => path.join(e.parentPath ?? e.path, e.name));
}

const SHARED_CONSUMERS = ["api/v1", "api/mcp"];

describe("serverless functions respect the api/ boundary", () => {
  it("no TypeScript sources under api/v1 or api/mcp", () => {
    // These need the shared core, so they must be CommonJS. A .ts file
    // here compiles fine locally and 500s in production.
    const ts = walk(apiDir)
      .filter((f) => f.endsWith(".ts") && !f.endsWith(".d.ts"))
      .map((f) => path.relative(repoRoot, f).split(path.sep).join("/"))
      .filter((f) => SHARED_CONSUMERS.some((d) => f.startsWith(`${d}/`)));

    expect(
      ts,
      `TypeScript under ${SHARED_CONSUMERS.join(" / ")} cannot reach shared/ at runtime ` +
        `and will return 500 FUNCTION_INVOCATION_FAILED. Write it as CommonJS .js and ` +
        `require("../_core.js").`,
    ).toEqual([]);
  });

  it("they reach shared code only through the api/_core.js bridge", () => {
    const files = walk(apiDir)
      .filter((f) => f.endsWith(".js"))
      .filter((f) => SHARED_CONSUMERS.some((d) =>
        path.relative(repoRoot, f).split(path.sep).join("/").startsWith(`${d}/`)));

    expect(files.length).toBeGreaterThan(0);

    for (const f of files) {
      const rel = path.relative(repoRoot, f).split(path.sep).join("/");
      const code = fs.readFileSync(f, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");
      const direct = code.match(/require\(["'][^"']*\/shared\/(?!dist\/api-core)[^"']*["']\)/g);
      expect(
        direct,
        `${rel} requires shared/ directly. Go through api/_core.js so there is one ` +
          `place the boundary is crossed.`,
      ).toBeNull();
    }
  });

  it("the bridge exists, is CommonJS, and requires the prebuilt bundle", () => {
    const bridge = path.join(apiDir, "_core.js");
    expect(fs.existsSync(bridge)).toBe(true);
    const src = fs.readFileSync(bridge, "utf8");
    expect(src).toMatch(/require\(["']\.\.\/shared\/dist\/api-core\.cjs["']\)/);
    expect(src).not.toMatch(/^\s*import\s/m);
  });

  it("every routable entrypoint ships the bundle in its deployment", () => {
    const cfg = JSON.parse(fs.readFileSync(path.join(repoRoot, "vercel.json"), "utf8"));
    const entrypoints = walk(apiDir)
      .filter((f) => f.endsWith(".js"))
      .map((f) => path.relative(repoRoot, f).split(path.sep).join("/"))
      .filter((f) => SHARED_CONSUMERS.some((d) => f.startsWith(`${d}/`)))
      .filter((f) => !path.basename(f).startsWith("_"));

    for (const rel of entrypoints) {
      const entry = cfg.functions?.[rel];
      expect(entry, `${rel} has no vercel.json functions entry`).toBeDefined();
      expect(
        String(entry.includeFiles ?? ""),
        `${rel} must includeFiles shared/dist/api-core.cjs or the bridge cannot resolve at runtime`,
      ).toContain("shared/dist/api-core.cjs");
    }
  });
});
