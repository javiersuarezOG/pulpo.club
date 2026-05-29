// POST /api/admin/newsletter/trigger-preview
//
// Body: { email, issue_number?: number, locale?: "en" | "es" }
//
// `issue_number` is optional. When omitted, defaults to "1" — matching the
// workflow's pre-existing default so calls without an explicit issue
// number behave exactly like the original endpoint. PR-NL-7a's
// "Upcoming sends" panel passes a per-row number so each scheduled
// Monday gets its own test send routable from the same admin button.
//
// `locale` is optional. When omitted, defaults to "en". The admin widget
// exposes a small EN/ES toggle so the operator can QA both language
// renders from the same surface.
//
// Triggers the `pulpo-newsletter` GitHub Actions workflow with
// `preview_cohorts=<email>`. The workflow runs the production Python
// pipeline (automation/newsletter/*) end-to-end and sends three real
// emails — one per cohort variant (anonymous, free_prefs, pro_prefs) —
// to the operator-supplied address. Subjects are prefixed
// `[PULPO PREVIEW · <cohort>]` so they're trivially distinguishable from
// real audience sends.
//
// Why a workflow dispatch and not a Node Resend call: the production
// renderer is Python, and we deliberately do not maintain a parallel
// Node renderer for the admin path (the half-finished `_render.js` is
// being removed alongside this endpoint). Routing through the same
// workflow real subscribers receive guarantees the preview matches the
// production cut byte-for-byte.
//
// Auth: deliberately none beyond rate-limiting. The real security
// perimeter is the GitHub PAT (`GITHUB_DISPATCH_TOKEN`, fine-grained,
// scoped `actions:write` on this repo only — cannot trigger arbitrary
// workflows or read anything). The worst an attacker can do is spam
// `[PULPO PREVIEW · <cohort>]`-subjected emails to the address they
// supply, capped by the rate limit at 15 emails/hr/IP. The bearer-token
// gate (PULPO_ADMIN_DEBUG_TOKEN) was removed after env-var-not-deployed
// friction kept blocking the operator on every iteration; the security
// trade was explicit and minor.
//
// Rate limit: 5 dispatches per IP per hour (this triggers a paid CI run
// AND a real Resend send — cheap insurance against a stuck-button loop).

const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DEFAULT_REPO = "javiersuarezOG/pulpo.club";
const DEFAULT_REF = "main";
const WORKFLOW_FILE = "pulpo-newsletter.yml";

const limiter = makeRateLimiter({
  windowMs: 60 * 60 * 1000,
  maxAttempts: 5,
  name: "admin_newsletter_trigger_preview",
});

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try {
    const chunks = [];
    for await (const chunk of req) chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
    const raw = Buffer.concat(chunks).toString("utf8");
    if (!raw) return {};
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function logApi(name, fields) {
  const parts = ["[api]", name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    logApi("admin.newsletter_trigger_preview", { status: 429, ms: Date.now() - t0 });
    return send429(res, rl, "admin_newsletter_trigger_preview");
  }

  const body = await readJsonBody(req);
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!email || !EMAIL_RE.test(email)) {
    return res.status(400).json({ error: "invalid_email" });
  }

  // Validate the optional issue_number — must be a positive integer in
  // a sane range. The default ("1") matches the workflow's pre-existing
  // default so backwards-compat is intact.
  let issueNumberStr = "1";
  if (body.issue_number !== undefined && body.issue_number !== null) {
    const n = Number(body.issue_number);
    if (!Number.isInteger(n) || n < 1 || n > 9999) {
      return res.status(400).json({
        error: "invalid_issue_number",
        hint: "issue_number must be a positive integer ≤ 9999.",
      });
    }
    issueNumberStr = String(n);
  }

  // Validate the optional locale — closed set, defaults to "en".
  let locale = "en";
  if (body.locale !== undefined && body.locale !== null) {
    const v = String(body.locale).toLowerCase();
    if (v !== "en" && v !== "es") {
      return res.status(400).json({
        error: "invalid_locale",
        hint: "locale must be 'en' or 'es'.",
      });
    }
    locale = v;
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN || "";
  if (!token) {
    logApi("admin.newsletter_trigger_preview", {
      status: 503, ms: Date.now() - t0, reason: "github_token_missing",
    });
    return res.status(503).json({
      error: "github_dispatch_not_configured",
      hint: "Set GITHUB_DISPATCH_TOKEN in Vercel env (fine-grained PAT, actions:write on this repo).",
    });
  }

  const repo = process.env.GITHUB_DISPATCH_REPO || DEFAULT_REPO;
  const ref = process.env.GITHUB_DISPATCH_REF || DEFAULT_REF;
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${WORKFLOW_FILE}/dispatches`;

  let gh;
  try {
    gh = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pulpo-admin-newsletter-preview",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          preview_cohorts: email,
          issue_number: issueNumberStr,
          preview_locale: locale,
        },
      }),
    });
  } catch (err) {
    logApi("admin.newsletter_trigger_preview", {
      status: 502, ms: Date.now() - t0, reason: "github_fetch_failed",
      error: (err && err.message) || "(no message)",
    });
    return res.status(502).json({
      error: "github_dispatch_failed",
      detail: (err && err.message) || "(no message)",
    });
  }

  if (gh.status !== 204) {
    const detail = await gh.text().catch(() => "");
    logApi("admin.newsletter_trigger_preview", {
      status: gh.status, ms: Date.now() - t0, reason: "github_non_204",
    });
    return res.status(gh.status === 404 ? 404 : 502).json({
      error: "github_dispatch_rejected",
      github_status: gh.status,
      detail: detail.slice(0, 500),
    });
  }

  logApi("admin.newsletter_trigger_preview", {
    status: 202, ms: Date.now() - t0,
    repo, ref, locale, email_domain: email.split("@")[1] || "",
  });

  return res.status(202).json({
    ok: true,
    repo,
    ref,
    workflow: WORKFLOW_FILE,
    runs_url: `https://github.com/${repo}/actions/workflows/${WORKFLOW_FILE}`,
    hint: "Three emails arrive in ~30–60s once the workflow picks up the dispatch. Subjects are prefixed [PULPO PREVIEW · <cohort>].",
  });
};
