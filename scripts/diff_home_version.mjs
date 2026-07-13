#!/usr/bin/env node
// Guardrail: any PR that touches a home block component (anything
// under `web/app/home/` that renders pixels) MUST also bump
// `web/app/home/versions.json`. Otherwise `/api/home/version` keeps
// serving the old version string for an experience that changed —
// downstream analytics + drift-detection silently break.
//
// This catches the failure mode the static `versions.test.ts` audit
// CAN'T catch:
//   * versions.test.ts asserts the SET of block ids in versions.json
//     matches BLOCK_ORDER — adds + removes only.
//   * this script asserts that when a component's render output
//     changes, its version string was bumped too.
//
// Usage:
//   node scripts/diff_home_version.mjs <BASE_SHA>
//
// Exit codes:
//   0 — either no home render file changed, OR versions.json was bumped
//   1 — home render file changed but versions.json was NOT bumped
//   2 — invocation / git error
//
// Scope intentionally tight:
//   * .jsx / .ts / .tsx / .js under `web/app/home/`
//   * EXCLUDES *.test.*, *.spec.*, and the versions.json file itself
//   * Does NOT include `web/app/styles/index.css` or `web/app/i18n.jsx`
//     — those are giant shared files used across the site; gating on
//     them would trip on every PR. Reviewers still flag visible
//     non-home-component changes when bumping versions.json is in
//     order. CLAUDE.md documents the policy.

import { execSync } from "node:child_process";

const BASE_SHA = process.argv[2];
if (!BASE_SHA) {
  console.error("Usage: node scripts/diff_home_version.mjs <BASE_SHA>");
  process.exit(2);
}

let changed;
try {
  // `<base>...HEAD` is the three-dot form Git uses for PR diffs:
  // changes on HEAD since it forked from <base>. Matches what GitHub
  // shows in the PR's "Files changed" tab.
  const out = execSync(`git diff --name-only ${BASE_SHA}...HEAD`, {
    encoding: "utf8",
    // 64MB: a huge diff (e.g. a mass photo-cache prune of 197k files)
    // overflows the default 1MB execSync buffer and false-fails the guard.
    maxBuffer: 64 * 1024 * 1024,
  });
  changed = out.trim().split("\n").filter(Boolean);
} catch (err) {
  console.error("git diff failed:", err.message);
  process.exit(2);
}

const VERSIONS_FILE = "web/app/home/versions.json";

function isHomeRenderChange(file) {
  if (!file.startsWith("web/app/home/")) return false;
  if (file === VERSIONS_FILE) return false;
  if (file.includes(".test.")) return false;
  if (file.includes(".spec.")) return false;
  return /\.(jsx?|tsx?)$/.test(file);
}

const homeRenderChanges = changed.filter(isHomeRenderChange);
const versionBumped = changed.includes(VERSIONS_FILE);

if (homeRenderChanges.length === 0) {
  console.log("[diff-home-version] no home render-file changes — OK");
  process.exit(0);
}

if (versionBumped) {
  console.log(
    `[diff-home-version] home render-file changes in ${homeRenderChanges.length} file(s) + versions.json bumped — OK\n` +
      `  changed:\n    - ${homeRenderChanges.join("\n    - ")}`,
  );
  process.exit(0);
}

console.error(
  "\n❌ [diff-home-version] Home component(s) changed without bumping " +
    VERSIONS_FILE +
    ".\n\n" +
    "Changed files:\n  - " +
    homeRenderChanges.join("\n  - ") +
    "\n\n" +
    "Fix: bump the affected block's version string in " +
    VERSIONS_FILE +
    ".\n" +
    'Example: \'"hero_v5": "v5"\' → \'"hero_v5": "v5.1"\'.\n\n' +
    "Why: /api/home/version reads versions.json; if the visible output " +
    "changes without bumping the version string, downstream analytics " +
    "+ drift-detection silently break.\n",
);
process.exit(1);
