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
//
// Dispatch verification: GitHub's `workflow_dispatch` POST returns 204
// once the payload is accepted, but the actual run is created
// asynchronously and CAN be silently dropped during GitHub Actions
// service hiccups (this bit us in production 2026-05-31 — the admin
// widget logged "✓ Sent" for a preview that never went out because no
// workflow ever ran). After GitHub returns 204 we poll the runs API
// for ~8s and only return 202 if a fresh run actually appears.
// Otherwise we return 502 `dispatch_accepted_but_no_run_created` so
// the widget surfaces a real error and the operator can retry.

const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");
const posthog = require("../../_posthog");
const { getLatestRunId, pollForNewerRun } = require("./_verify_dispatch");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DEFAULT_REPO = "javiersuarezOG/pulpo.club";
const DEFAULT_REF = "main";
const WORKFLOW_FILE = "pulpo-newsletter.yml";

// Closed set of newsletter IDs the widget registry can dispatch.
// Anything outside this list is rejected with `invalid_newsletter_id`
// so a typo / forged client can't quietly route a Pro · Weekly test
// through a "free-weekly" identity, polluting the audit trail.
// Coming-soon entries live here too — once their endpoints ship the
// widget will enable the cards and pick them up automatically.
const KNOWN_NEWSLETTER_IDS = new Set([
  "pro-weekly",
  "pro-welcome",     // coming soon — kept in the allowlist so the
  "free-welcome",    // future trigger doesn't need an API redeploy.
  "free-weekly",
  "free-welcome-back",
]);
const DEFAULT_NEWSLETTER_ID = "pro-weekly";

// Newsletter id → Python template id (the `--newsletter` value routed
// through automation/newsletter/templates::TEMPLATES). Passed to the
// workflow as `newsletter_template` so the same preview pipeline renders
// the right template — without this map every preview rendered as the Pro
// General master regardless of which card the operator clicked. Any id
// not listed falls back to the Pro General default in the workflow.
const TEMPLATE_FOR_NEWSLETTER = {
  "pro-weekly": "pulpo-pro-general",
  "free-weekly": "pulpo-free-general",
  // The free onboarding pair are render-only variants (welcome hero on the
  // free body), so a test-send is just rendering that template to the test
  // inbox via the same preview pipeline — no Clerk-coupled welcome dispatch
  // needed. (Their REAL trigger — homepage subscribe / Stripe / Resend —
  // is still a follow-up; this is the preview affordance only.)
  "free-welcome": "pulpo-free-welcome",
  "free-welcome-back": "pulpo-free-welcome-back",
};
const DEFAULT_TEMPLATE = "pulpo-pro-general";

// Fire a PostHog event so /api/admin/newsletter/recent-triggers can
// read the cross-device + cross-operator audit log back via HogQL.
// Best-effort + never blocks the response — the GitHub dispatch is the
// real action here, the event is an audit trail. capture() in
// api/_posthog.js is a silent no-op when POSTHOG_PROJECT_TOKEN is
// missing, so this works in any env.
//
// Includes the operator email as a property so the log shows WHO
// triggered. The widget passes it in the request body; the endpoint
// is intentionally auth-light (worst-case the property is spoofed to
// somebody else's name — not a real attack vector).
async function emitTriggerEvent({ to, locale, by, issueNumber, newsletterId, result, detail }) {
  try {
    posthog.capture(
      posthog.emailDistinctId(by || to),
      "admin.newsletter_test_triggered",
      {
        to,
        locale,
        by: by || null,
        issue_number: issueNumber,
        newsletter_id: newsletterId,     // "pro-weekly" / "pro-welcome" / …
        result,                          // "ok" | "error"
        detail: detail || null,          // populated on failure
        dispatched_at: new Date().toISOString(),
      },
    );
    await posthog.flush();
  } catch {
    /* never let telemetry block the dispatch response */
  }
}

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
  // Optional `by` — the operator's email (widget reads it from the
  // Clerk-mirrored localStorage blob). Stamped onto the PostHog
  // event so the cross-device log shows WHO triggered each test.
  const by = typeof body.by === "string" && EMAIL_RE.test(body.by.trim().toLowerCase())
    ? body.by.trim().toLowerCase()
    : null;

  // Optional newsletter_id — closed allow-list. Defaults to "pro-weekly"
  // for back-compat with the pre-registry trigger payload. Routes the
  // PostHog event so the cross-device log can filter / slice per type.
  let newsletterId = DEFAULT_NEWSLETTER_ID;
  if (body.newsletter_id !== undefined && body.newsletter_id !== null) {
    const v = String(body.newsletter_id);
    if (!KNOWN_NEWSLETTER_IDS.has(v)) {
      return res.status(400).json({
        error: "invalid_newsletter_id",
        hint: `newsletter_id must be one of: ${[...KNOWN_NEWSLETTER_IDS].join(", ")}.`,
      });
    }
    newsletterId = v;
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

  // Capture the newest existing workflow_dispatch run id BEFORE we
  // dispatch. After the dispatch returns 204, we poll for a run with a
  // larger id — that's the proof GitHub actually created the run, not
  // just accepted the dispatch payload. See _verify_dispatch.js for the
  // failure mode this guards against.
  const baselineRunId = await getLatestRunId({ repo, workflowFile: WORKFLOW_FILE, token });

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
          newsletter_template: TEMPLATE_FOR_NEWSLETTER[newsletterId] || DEFAULT_TEMPLATE,
        },
      }),
    });
  } catch (err) {
    logApi("admin.newsletter_trigger_preview", {
      status: 502, ms: Date.now() - t0, reason: "github_fetch_failed",
      error: (err && err.message) || "(no message)",
    });
    await emitTriggerEvent({
      to: email, locale, by, issueNumber: issueNumberStr, newsletterId,
      result: "error",
      detail: `github_dispatch_failed: ${(err && err.message) || "(no message)"}`,
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
    await emitTriggerEvent({
      to: email, locale, by, issueNumber: issueNumberStr, newsletterId,
      result: "error",
      detail: `github_status_${gh.status}: ${detail.slice(0, 200)}`,
    });
    return res.status(gh.status === 404 ? 404 : 502).json({
      error: "github_dispatch_rejected",
      github_status: gh.status,
      detail: detail.slice(0, 500),
    });
  }

  // GitHub returned 204 — the dispatch was accepted. But that does NOT
  // mean a run was created. Poll until a fresh run appears, or give up
  // and surface a 502 so the widget shows a real error instead of
  // falsely logging success.
  //
  // Skip verification (return 202 with verified=false) when we couldn't
  // get a baseline — that means GitHub's runs API was unavailable when
  // we tried, so failing-closed would surface a misleading error during
  // a wider GitHub outage. The baseline=null case is rare; the verify
  // failure case (got baseline, didn't see a newer run) is the one we
  // actually care about catching.
  if (baselineRunId !== null) {
    const newRun = await pollForNewerRun({
      repo, workflowFile: WORKFLOW_FILE, token, baselineId: baselineRunId,
    });
    if (!newRun) {
      logApi("admin.newsletter_trigger_preview", {
        status: 502, ms: Date.now() - t0, reason: "dispatch_accepted_but_no_run_created",
        baseline_run_id: baselineRunId,
      });
      await emitTriggerEvent({
        to: email, locale, by, issueNumber: issueNumberStr, newsletterId,
        result: "error",
        detail: "dispatch_accepted_but_no_run_created: GitHub returned 204 but no workflow run appeared within poll window",
      });
      return res.status(502).json({
        error: "dispatch_accepted_but_no_run_created",
        hint: "GitHub accepted the dispatch but no workflow run materialized within ~8s. This is usually a transient GitHub Actions issue — retry in ~30s. If it persists, check https://www.githubstatus.com.",
      });
    }
    logApi("admin.newsletter_trigger_preview", {
      status: 202, ms: Date.now() - t0,
      repo, ref, locale, email_domain: email.split("@")[1] || "",
      newsletter_id: newsletterId, run_id: newRun.id, verified: true,
    });
    await emitTriggerEvent({
      to: email, locale, by, issueNumber: issueNumberStr, newsletterId,
      result: "ok",
    });
    return res.status(202).json({
      ok: true,
      repo,
      ref,
      workflow: WORKFLOW_FILE,
      runs_url: newRun.html_url || `https://github.com/${repo}/actions/workflows/${WORKFLOW_FILE}`,
      run_id: newRun.id,
      verified: true,
      hint: "Email arrives in ~30–60s once the workflow finishes. Subject is prefixed [PULPO PREVIEW · pro_prefs].",
    });
  }

  logApi("admin.newsletter_trigger_preview", {
    status: 202, ms: Date.now() - t0,
    repo, ref, locale, email_domain: email.split("@")[1] || "",
    newsletter_id: newsletterId, verified: false, reason: "baseline_unavailable",
  });

  await emitTriggerEvent({
    to: email, locale, by, issueNumber: issueNumberStr, newsletterId,
    result: "ok",
  });

  return res.status(202).json({
    ok: true,
    repo,
    ref,
    workflow: WORKFLOW_FILE,
    runs_url: `https://github.com/${repo}/actions/workflows/${WORKFLOW_FILE}`,
    verified: false,
    hint: "Dispatch accepted; couldn't verify the run was created (GitHub runs API was unavailable). Watch the workflow page directly to confirm.",
  });
};
