#!/usr/bin/env node
/* check-contrast.mjs — WCAG contrast guard for tokens.css
 *
 * Reads web/app/styles/tokens.css, parses every oklch(...) variable,
 * converts to sRGB → relative luminance, then asserts critical
 * pairings meet WCAG ratios:
 *
 *   --ink     on --paper  ≥ 7   (AAA body)
 *   --ink-2   on --paper  ≥ 4.5 (AA body)
 *   --ink-3   on --paper  ≥ 4.5 (AA body)
 *   badges   on --paper   ≥ 3   (AA large/UI)
 *
 * Run via: npm run check:contrast
 * Exits 1 on any failure. CI gate from PR-1.5 onward.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const tokensPath = resolve(here, "tokens.css");
const css = readFileSync(tokensPath, "utf-8");

// --- Parse oklch tokens ---
const TOKEN_RE = /^\s*(--[a-z0-9-]+):\s*oklch\(([^)]+)\)\s*;/gim;
const tokens = new Map();
for (const m of css.matchAll(TOKEN_RE)) {
  const [_, name, args] = m;
  const parts = args.trim().split(/\s+/).map(Number);
  if (parts.length < 3 || parts.some(Number.isNaN)) continue;
  const [L, C, H] = parts;
  tokens.set(name, { L, C, H });
}

// --- oklch → sRGB (linear → gamma-encoded) ---
// Reference: https://www.w3.org/TR/css-color-4/#color-conversion-code
function oklchToSRGB({ L, C, H }) {
  const hRad = (H * Math.PI) / 180;
  const a = C * Math.cos(hRad);
  const b = C * Math.sin(hRad);
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;
  const l3 = l_ ** 3,
    m3 = m_ ** 3,
    s3 = s_ ** 3;
  const lr =
    +4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3;
  const lg =
    -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3;
  const lb =
    -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3;
  return [lr, lg, lb].map(linToSRGB);
}
function linToSRGB(c) {
  if (c <= 0.0031308) return 12.92 * c;
  return 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
}

// --- Relative luminance (WCAG) ---
function relLuminance(rgb) {
  const [r, g, b] = rgb.map((c) => {
    const lin =
      c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    return lin;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(l1, l2) {
  const [a, b] = [l1, l2].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

function ratio(fgName, bgName) {
  const fg = tokens.get(fgName);
  const bg = tokens.get(bgName);
  if (!fg || !bg) {
    return { ok: false, reason: `missing token (${fgName} or ${bgName})` };
  }
  const lFg = relLuminance(oklchToSRGB(fg));
  const lBg = relLuminance(oklchToSRGB(bg));
  return { ok: true, value: contrast(lFg, lBg) };
}

// --- Assertions ---
const checks = [
  { fg: "--ink", bg: "--paper", min: 7, label: "primary text (AAA)" },
  { fg: "--ink-2", bg: "--paper", min: 4.5, label: "secondary text (AA)" },
  { fg: "--ink-3", bg: "--paper", min: 4.5, label: "tertiary text (AA)" },
  { fg: "--paper", bg: "--accent", min: 4.5, label: "white-on-accent (AA)" },
  { fg: "--paper", bg: "--accent-strong", min: 4.5, label: "white-on-accent-strong (AA)" },
  { fg: "--paper", bg: "--badge-drop", min: 3, label: "badge: price drop" },
  { fg: "--paper", bg: "--badge-new", min: 3, label: "badge: new" },
  { fg: "--paper", bg: "--badge-ready", min: 3, label: "badge: build-ready" },
  { fg: "--paper", bg: "--badge-motivated", min: 3, label: "badge: motivated" },
  { fg: "--paper", bg: "--badge-off", min: 3, label: "badge: off-market" },
];

let failed = 0;
console.log("WCAG contrast check (tokens.css)\n");
for (const c of checks) {
  const r = ratio(c.fg, c.bg);
  if (!r.ok) {
    console.log(`  ✗ ${c.label.padEnd(36)} — ${r.reason}`);
    failed++;
    continue;
  }
  const pass = r.value >= c.min;
  if (!pass) failed++;
  console.log(
    `  ${pass ? "✓" : "✗"} ${c.label.padEnd(36)} ${r.value.toFixed(2)} (need ${c.min}, ${c.fg} on ${c.bg})`
  );
}

if (failed) {
  console.error(`\n${failed} contrast check(s) failed.`);
  process.exit(1);
}
console.log("\nAll contrast checks passed.");
