// THE api/ IMPORT BOUNDARY — the rule that actually took production down.
//
// INCIDENT (2026-08-25). Every /api/v1/* and /api/mcp endpoint returned
// 500 FUNCTION_INVOCATION_FAILED while CI was fully green and the
// website was fine.
//
// Cause, established by deploying eight probe functions to a preview
// and bisecting:
//
//   probe0  CommonJS, no imports                        200
//   probe1  TS, no imports, export default              200
//   probe2  TS, no imports, module.exports              200
//   probe4  TS imports api/_rate_limit.js  (inside)     200
//   probe5  TS imports a .ts             (inside)       200
//   probe3  TS imports shared/*.ts       (OUTSIDE)      500  <--
//   probe6  TS imports plain .js         (OUTSIDE)      500  <--
//   probe7  CommonJS require()s          (OUTSIDE)      200
//
// So: Vercel compiles TypeScript functions only for files INSIDE api/.
// Anything a .ts function imports from beyond that tree is never
// compiled into the bundle and the function dies at load. It is not
// about TypeScript, the file extension, or ESM vs CommonJS — a plain
// `require()` across the very same boundary is fine, because those are
// resolved by the file tracer rather than the compiler.
//
// The earlier module-format theory (and the api/tsconfig.json written
// for it) was wrong; probe1/2/5 disprove it and that test was deleted.
//
// WHY THIS TEST AND NOT A BEHAVIOURAL ONE: unit tests import the
// TypeScript SOURCE through Vite, which resolves ../../shared happily.
// The failure exists only in Vercel's emitted bundle. No test that
// imports the source can see it, so the invariant has to be asserted
// against the import graph itself.
//
// The sanctioned way to reach shared code is api/_core.js — CommonJS,
// inside api/, requiring the prebuilt shared/dist/api-core.cjs.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const apiDir = path.join(repoRoot, "api");

/** Every TypeScript file Vercel will compile under api/. `.d.ts` is
 *  excluded: declarations are erased at compile time and never loaded,
 *  so they may reference outside api/ safely. */
function apiTypeScriptFiles() {
  return fs
    .readdirSync(apiDir, { recursive: true, withFileTypes: true })
    .filter((e) => e.isFile() && e.name.endsWith(".ts") && !e.name.endsWith(".d.ts"))
    .map((e) => path.join(e.parentPath ?? e.path, e.name));
}

/** Relative import/export specifiers, ignoring `import type` (also erased). */
function relativeValueSpecifiers(source) {
  const withoutTypeOnly = source.replace(/\bimport\s+type\s+[\s\S]*?from\s*["'][^"']+["']/g, "");
  const out = [];
  const re = /\b(?:import|export)\b[^;]*?from\s*["'](\.[^"']*)["']/g;
  let m;
  while ((m = re.exec(withoutTypeOnly))) out.push(m[1]);
  const bare = /\bimport\s*\(\s*["'](\.[^"']*)["']\s*\)/g;
  while ((m = bare.exec(withoutTypeOnly))) out.push(m[1]);
  return out;
}

describe("TypeScript functions never import across the api/ boundary", () => {
  const files = apiTypeScriptFiles();

  it("finds TypeScript functions to check (guards a vacuous pass)", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  for (const file of files) {
    const rel = path.relative(repoRoot, file);
    it(`${rel} resolves every value import inside api/`, () => {
      for (const spec of relativeValueSpecifiers(fs.readFileSync(file, "utf8"))) {
        const resolved = path.resolve(path.dirname(file), spec);
        expect(
          resolved.startsWith(apiDir + path.sep),
          `${rel} imports "${spec}", which resolves outside api/ to ` +
            `${path.relative(repoRoot, resolved)}. Vercel does not compile that file into ` +
            `the function bundle, so the endpoint will return 500 ` +
            `FUNCTION_INVOCATION_FAILED at load while CI stays green. ` +
            `Reach shared code through api/_core.js instead.`,
        ).toBe(true);
      }
    });
  }

  it("the sanctioned bridge exists and crosses the boundary via require()", () => {
    const bridge = path.join(apiDir, "_core.js");
    expect(fs.existsSync(bridge)).toBe(true);
    const src = fs.readFileSync(bridge, "utf8");
    // CommonJS require is the form proven to work across the boundary.
    expect(src).toMatch(/require\(["']\.\.\/shared\/dist\/api-core\.cjs["']\)/);
    expect(src).not.toMatch(/^\s*import\s/m);
  });

  it("the bridge's bundle is actually built by npm run build", () => {
    // If this drops out of the build script the bridge throws
    // "Cannot find module" and every endpoint 500s again.
    const pkg = JSON.parse(fs.readFileSync(path.join(repoRoot, "package.json"), "utf8"));
    expect(pkg.scripts.build).toContain("build_shared_cjs.mjs");
    expect(fs.existsSync(path.join(repoRoot, "scripts", "build_shared_cjs.mjs"))).toBe(true);
  });

  it("every TS function ships the bundle in its deployment", () => {
    const cfg = JSON.parse(fs.readFileSync(path.join(repoRoot, "vercel.json"), "utf8"));
    for (const file of files) {
      const rel = path.relative(repoRoot, file).split(path.sep).join("/");
      // Only routable entrypoints get a functions entry; helpers are
      // pulled in with their importer.
      if (rel.split("/").pop().startsWith("_")) continue;
      const entry = cfg.functions?.[rel];
      expect(entry, `${rel} has no vercel.json functions entry`).toBeDefined();
      expect(
        String(entry.includeFiles ?? ""),
        `${rel} must includeFiles shared/dist/api-core.cjs or the bridge cannot resolve`,
      ).toContain("shared/dist/api-core.cjs");
    }
  });
});
