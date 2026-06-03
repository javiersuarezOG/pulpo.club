#!/usr/bin/env node
/* check_mixed_imports.mjs — fail CI when Vite reports a mixed
 * static+dynamic import.
 *
 * Vite's warning when a module is in both import graphs is:
 *   (!) <abs path> is dynamically imported by <a>, <b> but also
 *       statically imported by <c>, <d>, dynamic import will not move
 *       module into another chunk.
 *
 * The mixed graph forces Vite to bundle the module into the entry
 * chunk, defeating the whole point of the dynamic import (route
 * splitting, lazy load). We caught this on stripe-checkout.js and
 * telemetry/perf.ts in PR-5B; this script guards the regression.
 *
 * Usage: `npm run build 2>&1 | node scripts/check_mixed_imports.mjs`
 * or pass the build log path as argv[2].
 *
 * Exits 1 if any mixed-import warning is detected, 0 otherwise. Prints
 * the offending lines for actionable error output.
 */

import { readFileSync } from "node:fs";

// Vite's literal phrasing is "dynamically imported by ... but also
// statically imported by". Match both orderings just in case.
const PATTERN = /(dynamically imported.*but also statically imported|statically imported.*but also dynamically imported)/;

function readInput() {
  const fromArg = process.argv[2];
  if (fromArg) {
    return readFileSync(fromArg, "utf8");
  }
  // Otherwise read from stdin.
  return readFileSync(0, "utf8");
}

const text = readInput();
const offenders = text.split("\n").filter((line) => PATTERN.test(line));

if (offenders.length === 0) {
  console.log("check_mixed_imports: no mixed static/dynamic imports detected.");
  process.exit(0);
}

console.error("check_mixed_imports: FOUND mixed static/dynamic imports — these defeat Vite chunk splitting:\n");
for (const line of offenders) {
  console.error(`  ${line}`);
}
console.error("\nFix: pick one mode for each offender. Static is OK if the module must load with its caller; dynamic is OK if it should split into its own chunk. Mixing both is never OK.");
process.exit(1);
