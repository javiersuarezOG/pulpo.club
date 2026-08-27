// shared/dist/api-core.cjs is COMMITTED, and this proves it matches source.
//
// Committing a build artifact is not free, and the reason is specific:
// the serverless functions require() this file at load, and every
// alternative depends on build ordering that cannot be verified before
// a deploy. Generating it during `npm run build` left it missing in a
// fresh checkout — CI's tests failed with MODULE_NOT_FOUND, and on
// Vercel it is the difference between a working endpoint and
// FUNCTION_INVOCATION_FAILED. Committing removes the ordering question
// entirely: the file is simply always there.
//
// The cost of a committed artifact is drift — source changes, bundle
// does not, and the deployed API quietly runs old logic. This test
// removes that cost by rebuilding and comparing byte-for-byte.
//
// If it fails: run `node scripts/build_shared_cjs.mjs` and commit the
// result alongside your shared/ change.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const bundlePath = path.join(repoRoot, "shared", "dist", "api-core.cjs");

describe("the committed shared bundle matches its source", () => {
  it("exists — the functions require() it at load", () => {
    expect(
      fs.existsSync(bundlePath),
      "shared/dist/api-core.cjs is missing. Every /api/v1 and /api/mcp endpoint " +
        "will return 500 FUNCTION_INVOCATION_FAILED. Run: node scripts/build_shared_cjs.mjs",
    ).toBe(true);
  });

  it("is byte-identical to a fresh build of shared/", () => {
    const committed = fs.readFileSync(bundlePath);
    execFileSync("node", [path.join(repoRoot, "scripts", "build_shared_cjs.mjs")], {
      cwd: repoRoot,
      stdio: "pipe",
    });
    const rebuilt = fs.readFileSync(bundlePath);

    if (!committed.equals(rebuilt)) {
      // Restore so a failing run does not leave the tree dirty.
      fs.writeFileSync(bundlePath, committed);
    }
    expect(
      committed.equals(rebuilt),
      "shared/dist/api-core.cjs is stale — shared/ changed without rebuilding it, so the " +
        "deployed API would run older logic than the website. Run: " +
        "node scripts/build_shared_cjs.mjs, then commit the result.",
    ).toBe(true);
  });

  it("is self-contained — no imports out of the bundle", () => {
    // The whole point: zero external resolution at runtime, so nothing
    // depends on Vercel's tracer following requires out of api/.
    const src = fs.readFileSync(bundlePath, "utf8");
    expect(src).not.toMatch(/\brequire\(["']\.\.?\//);
    expect(src).not.toMatch(/^\s*import\s+.*\s+from\s+["']\.\.?\//m);
  });
});
