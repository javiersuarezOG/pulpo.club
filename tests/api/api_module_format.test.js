// The module-format contract for TypeScript serverless functions.
//
// THE INCIDENT THIS ENCODES (2026-08-25)
// Every /api/v1/* and /api/mcp endpoint returned 500
// FUNCTION_INVOCATION_FAILED in production while CI was fully green and
// the website was fine. The functions died at module load with
// "SyntaxError: Cannot use import statement outside a module".
//
// The cause is a three-way interaction that no single file makes
// visible, which is why it needs a test rather than a comment:
//
//   1. api/package.json sets "type": "commonjs" (deliberately — every
//      api/*.js function is CJS, from an earlier incident).
//   2. @vercel/node computes
//        isEsm = ext is .mjs/.mts
//                || (pkg.type === "module" && ext is .js/.ts/.tsx)
//      ...so isEsm is FALSE for our .ts functions. Crucially, it only
//      forces compilerOptions.module when isEsm is TRUE.
//   3. It then resolves tsconfig.json by walking UP from the
//      entrypoint. Without api/tsconfig.json that reaches the repo
//      root, whose "module" is "ESNext".
//
// Net effect: ESM emitted into a directory Node treats as CommonJS.
//
// Nothing in CI could catch it. Unit tests import the TypeScript
// SOURCE through Vite, which happily handles ESM; the failure only
// exists in Vercel's emitted output. So this test asserts the
// CONFIGURATION invariant instead: whatever module format the api/
// tree declares, the tsconfig that Vercel will actually resolve must
// agree with it.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const apiDir = path.join(repoRoot, "api");

/**
 * Strip comments so JSON.parse can read a tsconfig/jsonc file.
 *
 * ORDER IS LOAD-BEARING: line comments must go FIRST. These configs
 * document paths like `/api/v1/*`, and that `/*` opens a phantom block
 * comment which then runs to the `*​/` inside a later glob such as
 * `"include": ["**​/*.ts"]` — swallowing the whole compilerOptions
 * block and yielding an empty object that silently fails every
 * assertion below. Stripping `//` lines first removes the decoys before
 * they can be mistaken for delimiters.
 *
 * The line-comment pattern is anchored to line start so a `//` inside
 * a string value (a URL, say) is left alone.
 */
function readJsonc(file) {
  const raw = fs.readFileSync(file, "utf8")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  return JSON.parse(raw);
}

/** Vercel's `walkParentDirs`: nearest file walking up toward repoRoot. */
function walkParentDirs(startDir, filename) {
  let dir = startDir;
  for (;;) {
    const candidate = path.join(dir, filename);
    if (fs.existsSync(candidate)) return candidate;
    if (dir === repoRoot) return null;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

/** Every TypeScript entrypoint Vercel will build under api/. */
function typescriptEntrypoints() {
  return fs
    .readdirSync(apiDir, { recursive: true, withFileTypes: true })
    .filter((e) => e.isFile() && e.name.endsWith(".ts"))
    .map((e) => path.join(e.parentPath ?? e.path, e.name));
}

/** @vercel/node's isEsm, transcribed. */
function isEsm(entrypoint) {
  const ext = path.extname(entrypoint);
  if (ext === ".mjs" || ext === ".mts") return true;
  const pkgPath = walkParentDirs(path.dirname(entrypoint), "package.json");
  const pkg = pkgPath ? readJsonc(pkgPath) : {};
  return pkg.type === "module" && [".js", ".ts", ".tsx"].includes(ext);
}

/** The `module` Vercel will compile with, following its own rules. */
function effectiveModule(entrypoint) {
  const tsconfigPath = walkParentDirs(path.dirname(entrypoint), "tsconfig.json");
  const declared = tsconfigPath
    ? readJsonc(tsconfigPath)?.compilerOptions?.module
    : undefined;
  // Vercel only defaults `module` when isEsm; otherwise the resolved
  // tsconfig's value is used verbatim.
  if (declared === undefined && isEsm(entrypoint)) return "nodenext";
  return { value: declared, tsconfigPath };
}

describe("TypeScript functions under api/ emit the format Node will run", () => {
  const entrypoints = typescriptEntrypoints();

  it("finds TypeScript entrypoints to check (guards a vacuous pass)", () => {
    expect(entrypoints.length).toBeGreaterThan(0);
  });

  it("api/package.json still declares commonjs", () => {
    // If this ever flips to "module", the expectation below flips too —
    // the point is that the two must agree, not that either is sacred.
    expect(readJsonc(path.join(apiDir, "package.json")).type).toBe("commonjs");
  });

  it("api/tsconfig.json exists and is the nearest tsconfig for every entrypoint", () => {
    const apiTsconfig = path.join(apiDir, "tsconfig.json");
    expect(fs.existsSync(apiTsconfig)).toBe(true);
    for (const entry of entrypoints) {
      const resolved = walkParentDirs(path.dirname(entry), "tsconfig.json");
      expect(
        resolved,
        `${path.relative(repoRoot, entry)} would resolve ${path.relative(repoRoot, resolved ?? "")} ` +
          `instead of api/tsconfig.json`,
      ).toBe(apiTsconfig);
    }
  });

  for (const entry of typescriptEntrypoints()) {
    const rel = path.relative(repoRoot, entry);
    it(`${rel} compiles to CommonJS, matching api/package.json`, () => {
      const { value, tsconfigPath } = effectiveModule(entry);
      expect(
        String(value).toLowerCase(),
        `${rel} would be emitted as "${value}" per ` +
          `${path.relative(repoRoot, tsconfigPath ?? "(none)")}, but api/package.json ` +
          `declares "commonjs" — Node would throw "Cannot use import statement ` +
          `outside a module" at load and the function would 500.`,
      ).toBe("commonjs");
    });
  }

  it("the local typecheck project agrees with what ships", () => {
    // tsconfig.api.json typechecks these same files. If it validated
    // them as ESM it would be checking a shape that never deploys.
    const local = readJsonc(path.join(repoRoot, "tsconfig.api.json"));
    expect(String(local.compilerOptions.module).toLowerCase()).toBe("commonjs");
  });
});
