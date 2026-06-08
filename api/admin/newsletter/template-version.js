// GET /api/admin/newsletter/template-version
//
// Returns the current template version + last-updated date for each
// registered newsletter, derived directly from the Python source of
// truth (automation/newsletter/components/_common.py) at the time of
// the request.
//
// Why this exists: the admin widget (web/app/admin/widgets/newsletter
// /NewsletterWidget.jsx) used to carry a hardcoded TEMPLATE_VERSIONS
// mirror that had to be manually bumped in lock-step with every Python
// TEMPLATE_VERSION change. That mirror could drift between the
// in-flight PR moment and CI, and forced a second file edit on every
// template revision. This endpoint eliminates the mirror entirely:
// the widget fetches at mount, the Python file is the single source
// of truth, drift becomes structurally impossible.
//
// Implementation: the deployed function reads
// automation/newsletter/components/_common.py from disk (Vercel
// deploys the whole repo, so the Python file is colocated with the
// JS function bundle) and regex-extracts TEMPLATE_VERSION +
// LAST_UPDATED. No Python runtime needed.
//
// Response shape:
//   { "pulpo-pro-general": { version: "v4.4", lastUpdated: "2026-06-01" } }
//
// Cache: Cache-Control: public, max-age=300 — template versions
// change at most a couple of times per month. 5 min is generous and
// keeps the admin page snappy. Forcing a refresh after a template
// bump is a hard refresh or a 5-min wait; both acceptable.
//
// Degraded mode: if the Python file can't be read (deployment drift,
// path mismatch) we return 500 + a diagnostic field. The widget
// renders `—` for the version chrome rather than a misleading hardcoded
// value.

const fs = require("fs");
const path = require("path");

// Single source of truth. Each named template here gets one Python
// constant pair in `automation/newsletter/components/_common.py`:
//   • TEMPLATE_VERSION + LAST_UPDATED                          → pulpo-pro-general
//   • WELCOME_TEMPLATE_VERSION + WELCOME_LAST_UPDATED          → pulpo-pro-welcome
//   • WELCOME_BACK_TEMPLATE_VERSION + WELCOME_BACK_LAST_UPDATED → pulpo-pro-welcome-back
// Adding a future template (free-weekly, free-welcome, …) = one more
// constant pair in _common.py + one more `TEMPLATES` row below.
const COMMON_PY_PATH = path.join(
  process.cwd(),
  "automation",
  "newsletter",
  "components",
  "_common.py",
);

// Regexes are anchored at line-start with the `m` flag so
// WELCOME_TEMPLATE_VERSION can't accidentally match the
// TEMPLATE_VERSION extractor (or vice versa). The line-start anchor
// also prevents docstring mentions of these names from being matched
// as live assignments.
const TEMPLATES = [
  {
    id: "pulpo-pro-general",
    versionRe: /^TEMPLATE_VERSION\s*=\s*["']([^"']+)["']/m,
    lastUpdatedRe: /^LAST_UPDATED\s*=\s*["']([^"']+)["']/m,
  },
  {
    id: "pulpo-pro-welcome",
    versionRe: /^WELCOME_TEMPLATE_VERSION\s*=\s*["']([^"']+)["']/m,
    lastUpdatedRe: /^WELCOME_LAST_UPDATED\s*=\s*["']([^"']+)["']/m,
  },
  {
    // The welcome-back is the welcome template's resubscribe sub-version,
    // but it carries its own version line so PostHog can slice it. The
    // `_BACK_` infix keeps the line-anchored regexes disjoint from the
    // plain WELCOME_* ones above (no accidental cross-match).
    id: "pulpo-pro-welcome-back",
    versionRe: /^WELCOME_BACK_TEMPLATE_VERSION\s*=\s*["']([^"']+)["']/m,
    lastUpdatedRe: /^WELCOME_BACK_LAST_UPDATED\s*=\s*["']([^"']+)["']/m,
  },
  {
    // Free-tier weekly. The `FREE_GENERAL_` prefix keeps these
    // line-anchored regexes disjoint from the General TEMPLATE_VERSION /
    // LAST_UPDATED ones (which would otherwise substring-match).
    id: "pulpo-free-general",
    versionRe: /^FREE_GENERAL_TEMPLATE_VERSION\s*=\s*["']([^"']+)["']/m,
    lastUpdatedRe: /^FREE_GENERAL_LAST_UPDATED\s*=\s*["']([^"']+)["']/m,
  },
  {
    // Free onboarding pair. `FREE_WELCOME_` / `FREE_WELCOME_BACK_` prefixes
    // are disjoint at line-start (BACK_ never matches the plain one).
    id: "pulpo-free-welcome",
    versionRe: /^FREE_WELCOME_TEMPLATE_VERSION\s*=\s*["']([^"']+)["']/m,
    lastUpdatedRe: /^FREE_WELCOME_LAST_UPDATED\s*=\s*["']([^"']+)["']/m,
  },
  {
    id: "pulpo-free-welcome-back",
    versionRe: /^FREE_WELCOME_BACK_TEMPLATE_VERSION\s*=\s*["']([^"']+)["']/m,
    lastUpdatedRe: /^FREE_WELCOME_BACK_LAST_UPDATED\s*=\s*["']([^"']+)["']/m,
  },
];

// Short-version extractor handles both `-v4.4-` (pro) and
// `free-general-v1.0-` (free). The `SHORT_VERSION_RE` below pulls the
// `vN.N` token regardless of prefix.

// Extract the "v4.4" / "v1.0" portion from the full Python constant
// string so the widget can render the short form.
const SHORT_VERSION_RE = /-(v\d+\.\d+)-/;

function logApi(fields) {
  const parts = ["[api]", "admin.newsletter.template-version"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

module.exports = async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    logApi({ status: 405, ms: Date.now() - t0, reason: "method" });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  let raw;
  try {
    raw = fs.readFileSync(COMMON_PY_PATH, "utf8");
  } catch (err) {
    logApi({
      status: 500, ms: Date.now() - t0,
      reason: "common_py_unreadable",
      err_code: err.code || "unknown",
    });
    return res.status(500).json({
      error: "template_version_unavailable",
      diagnostic: `cannot read ${COMMON_PY_PATH}`,
    });
  }

  const out = {};
  const missing = [];
  for (const { id, versionRe, lastUpdatedRe } of TEMPLATES) {
    const versionMatch = raw.match(versionRe);
    const lastUpdatedMatch = raw.match(lastUpdatedRe);
    if (!versionMatch || !lastUpdatedMatch) {
      missing.push({
        id,
        has_version: !!versionMatch,
        has_last_updated: !!lastUpdatedMatch,
      });
      continue;
    }
    const fullVersion = versionMatch[1];
    const shortMatch = fullVersion.match(SHORT_VERSION_RE);
    out[id] = {
      version: shortMatch ? shortMatch[1] : fullVersion,
      lastUpdated: lastUpdatedMatch[1],
      fullVersion,
    };
  }

  // The General template's row is structurally load-bearing — the
  // widget falls back to "—" placeholders for missing keys, but a
  // missing General row would mean the weekly digest's version chrome
  // never renders. Treat that as a 500 (deployment drift). Welcome
  // and future templates degrade gracefully (their card shows "—").
  if (!out["pulpo-pro-general"]) {
    logApi({
      status: 500, ms: Date.now() - t0,
      reason: "extraction_failed",
      missing: JSON.stringify(missing),
    });
    return res.status(500).json({
      error: "template_version_unparseable",
      diagnostic: "TEMPLATE_VERSION or LAST_UPDATED regex did not match for pulpo-pro-general",
      missing,
    });
  }

  res.setHeader("Cache-Control", "public, max-age=300");
  logApi({
    status: 200, ms: Date.now() - t0,
    templates: Object.keys(out).join(","),
    general_version: out["pulpo-pro-general"].version,
    welcome_version: (out["pulpo-pro-welcome"] && out["pulpo-pro-welcome"].version) || "missing",
    welcome_back_version: (out["pulpo-pro-welcome-back"] && out["pulpo-pro-welcome-back"].version) || "missing",
    free_general_version: (out["pulpo-free-general"] && out["pulpo-free-general"].version) || "missing",
  });
  return res.status(200).json(out);
};
