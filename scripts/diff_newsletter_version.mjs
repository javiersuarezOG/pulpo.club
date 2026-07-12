#!/usr/bin/env node
// Guardrail: any PR that touches a newsletter template module (any
// Python source under `automation/newsletter/`) MUST also bump the
// corresponding version constant in
// `automation/newsletter/components/_common.py`:
//
//   * TEMPLATE_VERSION         (+ LAST_UPDATED)         → pulpo-pro-general
//   * WELCOME_TEMPLATE_VERSION (+ WELCOME_LAST_UPDATED) → pulpo-pro-welcome
//
// Without this, `/api/admin/newsletter/template-version` (which reads
// those constants verbatim from the Python source) keeps serving the
// old version for a template that already shipped a change — the
// admin widget shows wrong info, dispatched emails carry a stale
// version stamp, and drift between repo + warehouse becomes silent.
//
// Usage:
//   node scripts/diff_newsletter_version.mjs <BASE_SHA>
//
// Exit codes:
//   0 — either no newsletter-render file changed, OR _common.py was
//       touched (we trust the reviewer to actually move a version
//       constant in the same edit — a smarter line-level check is a
//       future enhancement)
//   1 — newsletter file changed but _common.py was NOT touched
//   2 — invocation / git error
//
// Scope:
//   * .py files under `automation/newsletter/`
//   * Plus .html / .css template assets if any live there
//   * EXCLUDES `_common.py` itself (it IS the source of truth) and
//     test/spec files

import { execSync } from "node:child_process";

const BASE_SHA = process.argv[2];
if (!BASE_SHA) {
  console.error("Usage: node scripts/diff_newsletter_version.mjs <BASE_SHA>");
  process.exit(2);
}

let changed;
try {
  const out = execSync(`git diff --name-only ${BASE_SHA}...HEAD`, {
    encoding: "utf8",
  });
  changed = out.trim().split("\n").filter(Boolean);
} catch (err) {
  console.error("git diff failed:", err.message);
  process.exit(2);
}

const COMMON_PY = "automation/newsletter/components/_common.py";

// Operational (non-render) newsletter modules. These orchestrate WHO gets a
// send and WHEN — they own no email HTML/CSS and no version constant, so
// changing them can't make a dispatched email's version stamp stale. (A module
// that merely *calls* `template.render()` still owns no template content: the
// HTML/CSS + version constants live in templates/ + components/ + _common.py,
// and subject lines are guarded separately by i18n_lint.) Editing one must NOT
// require a TEMPLATE_VERSION bump — that would falsely stamp every
// pro-general/welcome email as a new template revision. Render modules — the
// templates/, components/, render_html, i18n — are NOT in this list and stay
// guarded.
const NON_RENDER_MODULES = new Set([
  "automation/newsletter/welcome_reconcile.py",
  "automation/newsletter/free_welcome_reconcile.py",
  // Recipient selection (audience join) — produces a list, zero HTML.
  "automation/newsletter/subscribers.py",
  // Welcome/welcome-back dispatch orchestration — picks variant + subject
  // and stamps Clerk metadata; the HTML it sends comes from the guarded
  // pulpo_pro_welcome* template modules, which it only invokes.
  "automation/newsletter/welcome_dispatch.py",
  // Transport: transmits the already-rendered HTML it is GIVEN (Resend POST,
  // retries, idempotency key, List-Unsubscribe headers, plain-text
  // derivation). Owns no HTML/CSS template and no TEMPLATE_VERSION constant,
  // so a wire-level change (e.g. the Resend Idempotency-Key) must NOT force a
  // template-revision bump — that would falsely stamp every email as a new
  // template version. The HTML + version constants live in components/ +
  // templates/ + _common.py, which stay guarded.
  "automation/newsletter/send.py",
  // Issue-number counter — reads/advances the committed
  // newsletter_issue_state.json and (legacy) queries PostHog. Produces an
  // integer, zero HTML; changing it can't stale a template version.
  "automation/newsletter/issue_state.py",
  // Free-member filter codec — pure string encode/decode of the Resend
  // last_name side-channel (api/_prefs_codec.js is its JS twin). Owns no
  // HTML/CSS and no version constant; parity is guarded by its own contract
  // test, so a codec edit must NOT force a template-revision bump.
  "automation/newsletter/prefs_codec.py",
]);

function isNewsletterRenderChange(file) {
  if (!file.startsWith("automation/newsletter/")) return false;
  if (file === COMMON_PY) return false;
  if (NON_RENDER_MODULES.has(file)) return false;
  // Exclude tests at any depth.
  if (file.includes("/tests/")) return false;
  if (/test_|_test\./.test(file)) return false;
  if (/\.test\.|\.spec\./.test(file)) return false;
  // Only source-of-output files. Markdown / JSON inside the newsletter
  // tree (docs / fixtures) don't change the rendered email.
  return /\.(py|html|css)$/.test(file);
}

const newsletterChanges = changed.filter(isNewsletterRenderChange);
const commonPyTouched = changed.includes(COMMON_PY);

if (newsletterChanges.length === 0) {
  console.log("[diff-newsletter-version] no newsletter render-file changes — OK");
  process.exit(0);
}

if (commonPyTouched) {
  console.log(
    `[diff-newsletter-version] newsletter changes in ${newsletterChanges.length} file(s) + _common.py touched — OK\n` +
      `  changed:\n    - ${newsletterChanges.join("\n    - ")}`,
  );
  process.exit(0);
}

console.error(
  "\n❌ [diff-newsletter-version] Newsletter file(s) changed without touching " +
    COMMON_PY +
    ".\n\n" +
    "Changed files:\n  - " +
    newsletterChanges.join("\n  - ") +
    "\n\n" +
    "Fix: bump the affected template version in " +
    COMMON_PY +
    ":\n" +
    "  * TEMPLATE_VERSION         (+ LAST_UPDATED)         → pulpo-pro-general\n" +
    "  * WELCOME_TEMPLATE_VERSION (+ WELCOME_LAST_UPDATED) → pulpo-pro-welcome\n\n" +
    "Why: /api/admin/newsletter/template-version reads those constants " +
    "verbatim. Without a bump, the admin widget shows stale info and " +
    "dispatched emails carry a stale version stamp.\n",
);
process.exit(1);
