#!/usr/bin/env node
/* check-bundle-size.mjs — alarm-not-block bundle-size guard
 *
 * Asserts the production JS + CSS gzip sizes stay under the budgets
 * declared in the plan (PR-1.5):
 *   JS  ≤ 250 KB raw / 90 KB gzip
 *   CSS ≤ 80 KB raw / 16 KB gzip
 *
 * Reports actual sizes regardless. Exits 0 always (alarm-not-block per
 * the plan) but logs a clear warning when over budget so the PR
 * description picks it up.
 *
 * Run via: npm run check:size
 * Run after: npm run build
 */

import { readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, "../../../web/dist/assets");

const targets = [
  { path: "index.js", raw_kb: 250, gz_kb: 90 },
  { path: "index.css", raw_kb: 80, gz_kb: 16 },
];

let warned = 0;
console.log("Bundle-size budget check\n");
for (const t of targets) {
  const file = resolve(dist, t.path);
  let bytes;
  try {
    bytes = readFileSync(file);
  } catch (err) {
    console.log(`  ? ${t.path.padEnd(12)} not built — run \`npm run build\` first`);
    warned++;
    continue;
  }
  const raw = bytes.length / 1024;
  const gz = gzipSync(bytes).length / 1024;
  const okRaw = raw <= t.raw_kb;
  const okGz = gz <= t.gz_kb;
  const ok = okRaw && okGz;
  if (!ok) warned++;
  console.log(
    `  ${ok ? "✓" : "!"} ${t.path.padEnd(12)} ${raw.toFixed(1)}KB raw (≤${t.raw_kb})  ${gz.toFixed(1)}KB gz (≤${t.gz_kb})`
  );
}

if (warned) {
  console.log(`\n${warned} budget warning(s). Alarm-not-block — PR can still merge.`);
} else {
  console.log("\nAll bundles within budget.");
}
