#!/usr/bin/env node
/* check-bundle-size.mjs — Vite manifest bundle-size guard
 *
 * Reads web/dist/.vite/manifest.json after `npm run build` and reports
 * raw + gzip sizes for hashed Vite chunks. Budget breaches are
 * alarm-only by default (exit 0) for the two-week ramp; pass --strict
 * to make breaches fail CI. Missing build artifacts remain hard
 * failures because the guard cannot produce a truthful report.
 *
 * Run via: npm run check:size
 * Strict mode: npm run check:size -- --strict
 */

import { existsSync, readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import { basename, dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../../..");
const defaultDist = resolve(repoRoot, "web/dist");
const defaultManifest = resolve(defaultDist, ".vite/manifest.json");

const KB = 1024;

const BUDGETS = [
  { kind: "main_js", pattern: /^index-[\w-]+\.js$/, raw_kb: 480, gz_kb: 145 },
  { kind: "main_css", pattern: /^index-[\w-]+\.css$/, raw_kb: 180, gz_kb: 32 },
  { kind: "clerk_bundle", pattern: /^clerk-bundle-[\w-]+\.js$/, gz_kb: 120 },
  { kind: "account_route", pattern: /^account-[\w-]+\.js$/, gz_kb: 40 },
  { kind: "admin_route", pattern: /^AdminShell-[\w-]+\.js$/, gz_kb: 40 },
  { kind: "shelves_chunk", pattern: /^shelves-[\w-]+\.js$/, gz_kb: 40 },
  { kind: "start_route", pattern: /^start-[\w-]+\.js$/, gz_kb: 40 },
  { kind: "vendor_react", pattern: /^vendor-react-[\w-]+\.js$/, gz_kb: 55 },
];

function unique(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

export function classifyAsset(file) {
  const name = basename(file);
  const budget = BUDGETS.find((b) => b.pattern.test(name));
  if (budget) return budget;
  if (name.endsWith(".js")) return { kind: "unbudgeted_js" };
  if (name.endsWith(".css")) return { kind: "unbudgeted_css" };
  return { kind: "ignored" };
}

export function collectBundleFiles(manifest) {
  const files = [];
  for (const entry of Object.values(manifest)) {
    if (!entry || typeof entry !== "object") continue;
    if (typeof entry.file === "string") files.push(entry.file);
    if (Array.isArray(entry.css)) files.push(...entry.css);
  }
  return unique(files).filter((file) => /\.(js|css)$/.test(file));
}

export function summarizeBundle({ manifest, distDir }) {
  const files = collectBundleFiles(manifest);
  return files.map((file) => {
    const abs = resolve(distDir, file);
    const classification = classifyAsset(file);
    const exists = existsSync(abs);
    const rawBytes = exists ? statSync(abs).size : 0;
    const bytes = exists ? readFileSync(abs) : Buffer.alloc(0);
    const gzBytes = exists ? gzipSync(bytes).length : 0;
    const rawKb = rawBytes / KB;
    const gzKb = gzBytes / KB;
    const overRaw = classification.raw_kb ? rawKb > classification.raw_kb : false;
    const overGz = classification.gz_kb ? gzKb > classification.gz_kb : false;
    return {
      file,
      kind: classification.kind,
      raw_kb: Number(rawKb.toFixed(2)),
      gz_kb: Number(gzKb.toFixed(2)),
      raw_budget_kb: classification.raw_kb || null,
      gz_budget_kb: classification.gz_kb || null,
      exists,
      ok: exists && !overRaw && !overGz,
      over_raw: overRaw,
      over_gz: overGz,
    };
  }).sort((a, b) => {
    if (a.kind !== b.kind) return a.kind.localeCompare(b.kind);
    return a.file.localeCompare(b.file);
  });
}

export function formatText(rows, { strict = false } = {}) {
  const lines = ["Bundle-size budget check (Vite manifest)", ""];
  for (const row of rows) {
    const status = row.ok ? "✓" : "!";
    const rawBudget = row.raw_budget_kb ? `≤${row.raw_budget_kb}` : "unbudgeted";
    const gzBudget = row.gz_budget_kb ? `≤${row.gz_budget_kb}` : "unbudgeted";
    lines.push(
      `  ${status} ${row.kind.padEnd(16)} ${row.file.padEnd(34)} ${String(row.raw_kb).padStart(7)}KB raw (${rawBudget})  ${String(row.gz_kb).padStart(6)}KB gz (${gzBudget})`
    );
  }
  const warnings = rows.filter((row) => !row.ok).length;
  lines.push("");
  if (warnings) {
    lines.push(
      `${warnings} warning(s). ${strict ? "Strict mode will fail this run." : "Alarm-not-block — CI logs the report but does not fail on budget breaches yet."}`
    );
  } else {
    lines.push("All tracked bundles within budget.");
  }
  return lines.join("\n");
}

export function buildSummary(rows) {
  return {
    generated_at: new Date().toISOString(),
    warnings: rows.filter((row) => !row.ok).length,
    files: rows,
  };
}

function parseArgs(argv) {
  return {
    strict: argv.includes("--strict"),
    jsonOnly: argv.includes("--json"),
    manifestPath: defaultManifest,
    distDir: defaultDist,
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!existsSync(args.manifestPath)) {
    console.error(`Bundle-size manifest missing: ${args.manifestPath}`);
    console.error("Run `npm run build` first. Vite must emit build.manifest=true.");
    process.exit(1);
  }
  const manifest = JSON.parse(readFileSync(args.manifestPath, "utf8"));
  const rows = summarizeBundle({ manifest, distDir: args.distDir });
  const summary = buildSummary(rows);
  const failed = rows.some((row) => !row.ok);
  if (!args.jsonOnly) {
    console.log(formatText(rows, { strict: args.strict }));
    console.log("\nJSON summary:");
  }
  console.log(JSON.stringify(summary, null, 2));
  process.exit(args.strict && failed ? 1 : 0);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
