#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const base = process.argv[2];
if (!base) {
  console.error("usage: node scripts/diff_csp_allowlist.mjs <base-sha>");
  process.exit(2);
}

function readBaseVercel(ref) {
  try {
    return execFileSync("git", ["show", `${ref}:vercel.json`], { encoding: "utf8" });
  } catch (err) {
    console.error(`Could not read vercel.json at ${ref}: ${err.message}`);
    process.exit(2);
  }
}

function parseDomains(raw) {
  const json = JSON.parse(raw);
  const headers = Array.isArray(json.headers) ? json.headers : [];
  const values = [];
  for (const group of headers) {
    for (const h of group.headers || []) {
      if (h.key === "Content-Security-Policy" || h.key === "Content-Security-Policy-Report-Only") {
        values.push(String(h.value || ""));
      }
    }
  }
  const domains = new Set();
  for (const value of values) {
    for (const token of value.split(/\s+/)) {
      if (/^https?:\/\//.test(token)) domains.add(token.replace(/[;,]+$/, ""));
    }
  }
  return domains;
}

function changedDiffContainsJustification(ref) {
  try {
    const diff = execFileSync("git", ["diff", `${ref}...HEAD`, "--", "."], { encoding: "utf8" });
    return diff.split(/\r?\n/).some((line) => /^\+\s*# csp-drop:/.test(line));
  } catch {
    return false;
  }
}

const before = parseDomains(readBaseVercel(base));
const after = parseDomains(fs.readFileSync("vercel.json", "utf8"));
const dropped = [...before].filter((domain) => !after.has(domain)).sort();

if (dropped.length === 0) {
  console.log("CSP allowlist diff: no domains dropped.");
  process.exit(0);
}

if (changedDiffContainsJustification(base)) {
  console.log(`CSP allowlist diff: dropped ${dropped.join(", ")} with # csp-drop justification.`);
  process.exit(0);
}

console.error("CSP allowlist diff failed: domains were dropped without a paired '# csp-drop:' justification:");
for (const domain of dropped) console.error(`- ${domain}`);
process.exit(1);
