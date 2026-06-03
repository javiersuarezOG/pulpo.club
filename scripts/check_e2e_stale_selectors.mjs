#!/usr/bin/env node
/* Warn when retired E2E selectors appear outside quarantined legacy specs.
 *
 * First rollout is non-blocking: CI surfaces warnings but exits 0. The
 * intent is to keep critical specs honest while the full smoke suite is
 * being split into critical / responsive / legacy lanes.
 */

import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = process.cwd();
const e2eDir = resolve(root, "tests/e2e");
const patterns = [
  /\.hp-hero-v3/g,
  /\.hp-hero-v4/g,
  /\.hp-shoreline/g,
  /\.nl-widget/g,
  /\.usp-band-/g,
];

let unquarantined = 0;
let total = 0;

for (const name of readdirSync(e2eDir)) {
  if (!name.endsWith(".ts")) continue;
  const path = resolve(e2eDir, name);
  const text = readFileSync(path, "utf8");
  const legacy = text.includes("@legacy");
  const lines = text.split(/\r?\n/);
  lines.forEach((line, idx) => {
    const previous = lines[idx - 1] || "";
    if (line.includes("stale-selector-allowed") || previous.includes("stale-selector-allowed")) return;
    const matched = patterns.some((pattern) => {
      pattern.lastIndex = 0;
      return pattern.test(line);
    });
    if (!matched) return;
    total += 1;
    if (!legacy) {
      unquarantined += 1;
      console.warn(`::warning file=tests/e2e/${name},line=${idx + 1}::stale selector in non-legacy spec: ${line.trim()}`);
    }
  });
}

if (total === 0) {
  console.log("No retired E2E selectors found.");
} else {
  console.log(`Retired E2E selector scan: ${total} hit(s), ${unquarantined} outside @legacy specs.`);
}

process.exit(0);
