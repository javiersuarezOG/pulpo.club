// POST /api/admin/newsletter/trigger-audience-send
//
// Body: { confirm: "SEND", issue_number?: number, by?: string }
//
// Triggers a LIVE audience send — every Pro/Agency subscriber in the
// Resend audience receives Issue <issue_number> in their inbox. This is
// the "Send to everyone" button in the admin widget; the operator
// preview button uses trigger-preview.js instead.
//
// Guardrails (in this order, fail-fast):
//
//   1. Method must be POST.
//   2. Rate limit: 1 send per IP per hour. A double-click can't fire
//      two real sends. The window matches the operator's expected
//      cadence (weekly + hot-fix room).
//   3. `confirm` body field must be the literal string "SEND" — the
//      modal's type-to-confirm input is mirrored server-side so a
//      forged client can't skip the gate.
//   4. issue_number is required and validated (positive int ≤ 9999).
//   5. GITHUB_DISPATCH_TOKEN must be present (else 503).
//
// On success: dispatches the pulpo-newsletter workflow with
// `send_mode=yes`, `issue_number=<N>`. Fires a PostHog audit event
// `admin.newsletter_audience_send_triggered` carrying who, when, and
// how many. Returns { run_url_hint, dispatched_at } so the UI can
// link the operator to the workflow run.
//
// Auth: PULPO_ADMIN_DEBUG_TOKEN bearer via requireAdminAuth(), plus the
// SEND gate and 1/hour rate-limit. The GitHub PAT stays server-side.
//
// Dispatch verification: GitHub's workflow_dispatch POST returns 204
// on accepted payload, but the run is created async and can be
// silently dropped during transient GH Actions hiccups (bit us
// 2026-05-31 on the preview path; this path has higher blast radius —
// a falsely-claimed audience send means every Pro subscriber is
// silently skipped). After GitHub returns 2xx we poll the runs API
// for ~8s and only return 200 if a fresh run appears; otherwise 502
// `dispatch_accepted_but_no_run_created` so the modal shows a real
// error instead of "Sent Issue N to X readers."

const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");
const { requireAdminAuth } = require("../../_admin_auth");
const posthog = require("../../_posthog");
const { getLatestRunId, pollForNewerRun } = require("./_verify_dispatch");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DEFAULT_REPO = "javiersuarezOG/pulpo.club";
const DEFAULT_REF = "main";
const WORKFLOW_FILE = "pulpo-newsletter.yml";
const REQUIRED_CONFIRM_STRING = "SEND";

const limiter = makeRateLimiter({
  windowMs: 60 * 60 * 1000,                       // 1 hour
  maxAttempts: 1,                                 // one send per hour per IP
  name: "admin_newsletter_audience_send",
});

function logApi(fields) {
  const parts = ["[api]", "admin_newsletter_audience_send"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

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

async function emitAuditEvent({ by, issueNumber, result, detail, audienceCount }) {
  // Fire-and-forget audit trail. Never blocks the dispatch response.
  // PostHog dashboard can roll up
  // `admin.newsletter_audience_send_triggered` to answer "who sent
  // what, when" without crawling GitHub Actions UI.
  try {
    posthog.capture(
      posthog.emailDistinctId(by || "anonymous"),
      "admin.newsletter_audience_send_triggered",
      {
        by: by || null,
        issue_number: issueNumber,
        result,                                   // "ok" | "error"
        detail: detail || null,                   // populated on failure
        audience_count: audienceCount,            // null when not provided
        dispatched_at: new Date().toISOString(),
      },
    );
    await posthog.flush();
  } catch {
    /* never let telemetry block the dispatch response */
  }
}

module.exports = async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi({ status: 405, ms: Date.now() - t0, reason: "method", method: req.method });
    return res.status(405).json({ error: "method_not_allowed" });
  }
  if (!requireAdminAuth(req, res)) return;

  // Validation FIRST, rate-limit AFTER. The rate-limiter exists to
  // prevent runaway REAL sends (one per hour cap); it should only
  // count meaningful, well-formed POSTs that would actually trigger
  // a dispatch. The original ordering (rate-limit before validation)
  // burned the hour-long slot on a typo in the SEND input — a real
  // operator misclick that mistyped "Send" (lowercase) had to wait
  // an hour before retrying. Found in smoke-testing immediately
  // after PR #562 landed. The "admin abuse" attack vector this
  // ordering trades against is non-existent (admin-only surface,
  // no real attackers; CPU cost of validation is negligible).

  const body = await readJsonBody(req);

  // The literal "SEND" gate. Mirrors the modal's text input — a
  // forged or scripted POST that skips the input must still send this
  // exact string. Case-sensitive on purpose. Failing here does NOT
  // consume the rate-limit slot.
  const confirm = typeof body.confirm === "string" ? body.confirm : "";
  if (confirm !== REQUIRED_CONFIRM_STRING) {
    logApi({ status: 400, ms: Date.now() - t0, reason: "confirm_missing" });
    return res.status(400).json({
      error: "confirm_required",
      hint: `body.confirm must be the literal string "${REQUIRED_CONFIRM_STRING}".`,
    });
  }

  // issue_number is REQUIRED for audience sends. Default-1 would let a
  // misfire send last issue's content; force the operator to pass it.
  // Also fails before the rate-limit so a bad number doesn't burn the
  // slot.
  if (body.issue_number === undefined || body.issue_number === null) {
    logApi({ status: 400, ms: Date.now() - t0, reason: "issue_number_missing" });
    return res.status(400).json({
      error: "issue_number_required",
      hint: "issue_number is required for audience sends.",
    });
  }
  const issueNum = Number(body.issue_number);
  if (!Number.isInteger(issueNum) || issueNum < 1 || issueNum > 9999) {
    logApi({ status: 400, ms: Date.now() - t0, reason: "issue_number_invalid" });
    return res.status(400).json({
      error: "invalid_issue_number",
      hint: "issue_number must be a positive integer ≤ 9999.",
    });
  }
  const issueNumberStr = String(issueNum);

  // Rate limit NOW — only after we've confirmed this POST is the
  // well-formed real-send shape. A double-click on a valid request
  // still gets one 200 + one 429; a typo'd request gets a 400 and
  // the next attempt is free.
  const ip = ipFromRequest(req);
  const rl = limiter.hit(ip);
  if (!rl.allowed) {
    logApi({
      status: 429, ms: Date.now() - t0, reason: "rate_limited",
      retry_after_s: Math.ceil(rl.retryAfterMs / 1000),
    });
    return send429(res, rl, "admin_newsletter_audience_send");
  }

  // Optional `by` — operator email for the audit log. Same shape as
  // trigger-preview.js.
  const by = typeof body.by === "string" && EMAIL_RE.test(body.by.trim().toLowerCase())
    ? body.by.trim().toLowerCase()
    : null;

  // Optional audience_count carried from the modal's prior /audience-
  // count call. Stamped onto the audit event so the dashboard shows
  // what the operator THOUGHT they were sending to vs what actually
  // landed (the workflow logs the actual recipient count).
  const audienceCount = Number.isInteger(body.audience_count) ? body.audience_count : null;

  const token = process.env.GITHUB_DISPATCH_TOKEN || "";
  if (!token) {
    logApi({ status: 503, ms: Date.now() - t0, reason: "github_token_missing" });
    return res.status(503).json({
      error: "github_dispatch_not_configured",
      hint: "Set GITHUB_DISPATCH_TOKEN in Vercel env (fine-grained PAT, actions:write on this repo).",
    });
  }

  const repo = process.env.GITHUB_DISPATCH_REPO || DEFAULT_REPO;
  const ref = process.env.GITHUB_DISPATCH_REF || DEFAULT_REF;
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${WORKFLOW_FILE}/dispatches`;

  // Capture the newest existing workflow_dispatch run id BEFORE we
  // dispatch. Used by the post-dispatch verify-poll below to confirm
  // GitHub actually created a run (not just accepted the dispatch).
  // See api/admin/newsletter/_verify_dispatch.js for the failure mode
  // this guards against — bit us 2026-05-31 on the preview path, same
  // class of bug applies here with HIGHER blast radius (a missing
  // audience send is a silent skip of every Pro subscriber's weekly).
  const baselineRunId = await getLatestRunId({ repo, workflowFile: WORKFLOW_FILE, token });

  let gh;
  try {
    gh = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pulpo-admin-newsletter-audience-send",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          issue_number: issueNumberStr,
          send_mode: "yes",
        },
      }),
    });
  } catch (err) {
    logApi({
      status: 502, ms: Date.now() - t0, reason: "github_fetch_failed",
      error: (err && err.message) || "(no message)",
    });
    await emitAuditEvent({
      by, issueNumber: issueNumberStr, audienceCount,
      result: "error",
      detail: `github_dispatch_failed: ${(err && err.message) || "(no message)"}`,
    });
    return res.status(502).json({ error: "github_dispatch_failed" });
  }

  if (!gh.ok) {
    const text = await gh.text().catch(() => "(no body)");
    logApi({
      status: gh.status, ms: Date.now() - t0, reason: "github_dispatch_non_ok",
      body_snippet: text.slice(0, 200),
    });
    await emitAuditEvent({
      by, issueNumber: issueNumberStr, audienceCount,
      result: "error",
      detail: `github ${gh.status}: ${text.slice(0, 200)}`,
    });
    return res.status(502).json({
      error: "github_dispatch_rejected",
      status: gh.status,
    });
  }

  // GitHub accepted the dispatch (2xx). Now confirm the run actually
  // exists — otherwise we'd happily flash "Sent Issue N to X readers"
  // in the modal while no email goes out. Skip verification only when
  // we couldn't get a baseline (GitHub runs API unavailable); that
  // failure mode would falsely block dispatches during a wider GH
  // outage, which is worse than the rare missed verify.
  if (baselineRunId !== null) {
    const newRun = await pollForNewerRun({
      repo, workflowFile: WORKFLOW_FILE, token, baselineId: baselineRunId,
    });
    if (!newRun) {
      logApi({
        status: 502, ms: Date.now() - t0, reason: "dispatch_accepted_but_no_run_created",
        baseline_run_id: baselineRunId, issue: issueNumberStr,
      });
      await emitAuditEvent({
        by, issueNumber: issueNumberStr, audienceCount,
        result: "error",
        detail: "dispatch_accepted_but_no_run_created: GitHub returned 2xx but no workflow run appeared within poll window",
      });
      return res.status(502).json({
        error: "dispatch_accepted_but_no_run_created",
        hint: "GitHub accepted the dispatch but no workflow run materialized within ~8s. This is usually a transient GitHub Actions issue — retry in ~30s. If it persists, check https://www.githubstatus.com.",
      });
    }

    logApi({
      status: 200, ms: Date.now() - t0, op: "dispatch", issue: issueNumberStr,
      audience: audienceCount, by: by || "anon", run_id: newRun.id, verified: true,
    });

    await emitAuditEvent({
      by, issueNumber: issueNumberStr, audienceCount,
      result: "ok", detail: null,
    });

    return res.status(200).json({
      ok: true,
      issue_number: issueNum,
      audience_count: audienceCount,
      dispatched_at: new Date().toISOString(),
      runs_url_hint: newRun.html_url || `https://github.com/${repo}/actions/workflows/${WORKFLOW_FILE.replace(".yml", "")}`,
      run_id: newRun.id,
      verified: true,
    });
  }

  // Baseline unavailable — return success but flag the unverified
  // state so the UI can warn the operator to watch the workflow page.
  const runsUrlHint = `https://github.com/${repo}/actions/workflows/${WORKFLOW_FILE.replace(".yml", "")}`;

  logApi({
    status: 200, ms: Date.now() - t0, op: "dispatch", issue: issueNumberStr,
    audience: audienceCount, by: by || "anon", verified: false, reason: "baseline_unavailable",
  });

  await emitAuditEvent({
    by, issueNumber: issueNumberStr, audienceCount,
    result: "ok", detail: null,
  });

  return res.status(200).json({
    ok: true,
    issue_number: issueNum,
    audience_count: audienceCount,
    dispatched_at: new Date().toISOString(),
    runs_url_hint: runsUrlHint,
    verified: false,
  });
};
