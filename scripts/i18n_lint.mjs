#!/usr/bin/env node
// i18n static linter — two fast (<1s) checks that catch the most common i18n
// regressions in CI before the slower Playwright canary fires. The Playwright
// spec (tests/e2e/preview-smoke.spec.ts) covers rendered JSX text; this script
// covers what static analysis can see cheaply:
//
//   1. Hardcoded English in JSX attribute strings:
//        aria-label="..."  placeholder="..."  alt="..."  title="..."
//      (empty alt="" is fine for decorative imgs).
//
//   2. The "raw-enum render" trap — `{x.replace("_", " ")}` humanizes an enum
//      slug for display in EVERY locale, bypassing t(). This is the exact bug
//      behind the active-filter chip + table-header leaks. Scanned in JSX/TSX
//      render files only.
//
// A flagged literal/pattern is a bug (or, rarely, legitimate — a shared brand
// token, a capitalize() safety net after a closed-set t() guard, an SEO slug,
// or a dev-only control). Annotate those with `// i18n-allow: <reason>` on the
// same line (attribute check) or the same/preceding line (enum-render check).
// Anything else fails the build with a file:line and a remediation hint.
//
// Usage: `node scripts/i18n_lint.mjs` (zero deps).

import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "web/app");
const EXTENSIONS = new Set([".jsx", ".tsx", ".js", ".ts"]);

// Files we deliberately exclude. Each entry has a justification — keep
// this list small. The LegacySignupModal in pages.jsx is excluded only
// for the section between two pragma comments; see HARDCODED_LEGACY_*
// markers below if we ever want to scope-down further.
const SKIP_PATHS = [
  // Skip telemetry catalog comments — they reference English in /** docs
  "web/app/telemetry/events.ts",
  // Skip Vite-injected dev panel (DCE'd in prod)
  "web/app/tweaks-panel.jsx",
];

// Attributes that should always be a `t()` call when populated. We
// allow `aria-label={...}` (JS expression, presumed dynamic/i18n) and
// flag `aria-label="..."` (literal string).
const ATTRIBUTES = ["aria-label", "placeholder", "alt", "title"];

// "Looks like English" heuristic: starts with a capital letter, has at
// least one ASCII letter, contains at least one space OR is at least
// 4 chars long. Skip empty strings (alt="" is valid for decor imgs).
function looksLikeEnglish(s) {
  if (!s) return false;
  if (s.length < 2) return false;
  if (!/^[A-Z]/.test(s)) return false;
  if (!/[a-zA-Z]/.test(s)) return false;
  // Lower the false-positive rate: skip strings that are just one short
  // word and could be a programmatic ID (e.g. role="Button"). Real i18n
  // strings are usually multi-word or include punctuation.
  if (!/\s/.test(s) && s.length < 4) return false;
  return true;
}

function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walk(full);
    } else if (EXTENSIONS.has(path.extname(entry.name))) {
      const rel = path.relative(process.cwd(), full);
      if (SKIP_PATHS.some((p) => rel === p || rel.startsWith(p + "/"))) continue;
      yield full;
    }
  }
}

const ATTR_REGEX = new RegExp(
  // (\battr-name)=("...")
  String.raw`\b(${ATTRIBUTES.join("|")})="([^"]*)"`,
  "g",
);

let violations = 0;
const findings = [];

for (const file of walk(ROOT)) {
  const lines = fs.readFileSync(file, "utf8").split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // Per-line allow pragma — annotate when a literal is intentional
    // (e.g. an English brand name that's the same in both locales).
    if (line.includes("i18n-allow")) continue;
    let m;
    ATTR_REGEX.lastIndex = 0;
    while ((m = ATTR_REGEX.exec(line)) !== null) {
      const [, attr, value] = m;
      if (!looksLikeEnglish(value)) continue;
      findings.push({
        file: path.relative(process.cwd(), file),
        line: i + 1,
        attr,
        value,
        snippet: line.trim(),
      });
      violations++;
    }
  }
}

// ── Enum-render trap ──────────────────────────────────────────────────────
// `{x.replace("_", " ")}` humanizes an enum slug for display in EVERY locale,
// bypassing t() — the exact bug behind the active-filter chip + table-header
// leaks (raw "ocean view" / "price drop" shown to Spanish users). Catch the
// humanize pattern in JSX/TSX render files. A legitimate site (the capitalize()
// safety net AFTER a closed-set t() guard, an SEO slug, or a dev-only control)
// is exempted with `// i18n-allow: <reason>` on the same or preceding line.
const ENUM_RENDER_REGEX = /\.replace\(\s*(?:["'`]_["'`]|\/_\/[gimsuy]*)\s*,\s*["'` ]/;
const enumFindings = [];
for (const file of walk(ROOT)) {
  if (![".jsx", ".tsx"].includes(path.extname(file))) continue;
  const lines = fs.readFileSync(file, "utf8").split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (!ENUM_RENDER_REGEX.test(lines[i])) continue;
    const exempt =
      lines[i].includes("i18n-allow") || (i > 0 && lines[i - 1].includes("i18n-allow"));
    if (exempt) continue;
    enumFindings.push({
      file: path.relative(process.cwd(), file),
      line: i + 1,
      snippet: lines[i].trim(),
    });
  }
}

if (violations === 0 && enumFindings.length === 0) {
  console.log(
    "[i18n-lint] 0 hardcoded JSX attribute strings + 0 raw-enum renders under web/app/ ✓",
  );
  process.exit(0);
}

if (violations > 0) {
  console.error(`[i18n-lint] ${violations} hardcoded JSX attribute string(s) found:`);
  for (const f of findings) {
    console.error(`  ${f.file}:${f.line}  ${f.attr}="${f.value}"`);
    console.error(`    > ${f.snippet}`);
  }
  console.error("");
  console.error("Fix one of these ways:");
  console.error('  1. Add a row to web/app/i18n.jsx UI_STRINGS, then use t("your.key", locale).');
  console.error('  2. If the literal is shared between EN and ES (brand name etc.),');
  console.error('     append `// i18n-allow: <reason>` to the same line.');
  console.error("");
}

if (enumFindings.length > 0) {
  console.error(
    `[i18n-lint] ${enumFindings.length} raw-enum render(s) found (humanizing an enum slug bypasses t()):`,
  );
  for (const f of enumFindings) {
    console.error(`  ${f.file}:${f.line}`);
    console.error(`    > ${f.snippet}`);
  }
  console.error("");
  console.error("Fix: look the value up per-key via a closed-set t() guard (the road_access /");
  console.error("beachfront_tier pattern in CLAUDE.md → i18n). If legitimately exempt (the");
  console.error("capitalize() safety net after a t() guard, an SEO slug, or a dev-only control),");
  console.error("append `// i18n-allow: <reason>` to the same or preceding line.");
  console.error("");
}

console.error("See CLAUDE.md → \"i18n — every user-visible string goes through t()\".");
process.exit(1);
