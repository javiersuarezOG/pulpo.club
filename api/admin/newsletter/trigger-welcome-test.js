// POST /api/admin/newsletter/trigger-welcome-test
//
// Body: { email, by?, force?: boolean }
//
// Operator surface for the Pulpo Pro Welcome template. Dispatches the
// `pulpo-pro-welcome` GitHub Actions workflow with send_mode=yes,
// source=admin, and (by default) force=yes so the operator can
// re-render the welcome to themselves without manually clearing the
// recipient's Clerk publicMetadata.welcome_newsletter_sent_at.
//
// Mirrors the architecture of trigger-preview.js (the weekly's
// per-cohort preview surface):
//   • Same GITHUB_DISPATCH_TOKEN, repo, ref.
//   • Same rate limiter (5/hr/IP — paid CI run + real Resend send).
//   • Same _verify_dispatch.js poll for "did GitHub actually create
//     a run?" — guards against the silent-drop failure documented in
//     trigger-preview.js's preamble.
//   • Same PostHog `admin.newsletter_test_triggered` event so the
//     cross-device audit log shows welcome tests alongside weekly ones.
//
// What's different from trigger-preview:
//   • The welcome workflow targets a single recipient (no cohort fan-out).
//   • No locale input — the dispatcher reads locale from the recipient's
//     Clerk publicMetadata.profile.locale.
//   • No issue_number — the welcome is always "issue 1" in its own
//     telemetry namespace.
//   • `force` defaults to TRUE for this endpoint specifically. The
//     idempotency stamp is there to protect production (Stripe retries
//     etc.); the admin Test-send-to-me surface is for QA, where
//     re-rendering is the whole point.

const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");
const posthog = require("../../_posthog");
const { getLatestRunId, pollForNewerRun } = require("./_verify_dispatch");

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DEFAULT_REPO = "javiersuarezOG/pulpo.club";
const DEFAULT_REF = "main";
const WORKFLOW_FILE = "pulpo-pro-welcome.yml";

async function emitTriggerEvent({ to, by, force, result, detail }) {
  try {
    posthog.capture(
      posthog.emailDistinctId(by || to),
      "admin.newsletter_test_triggered",
      {
        to,
        by: by || null,
        newsletter_id: "pro-welcome",
        force,
        result,
        detail: detail || null,
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
  name: "admin_newsletter_trigger_welcome_test",
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
    logApi("admin.newsletter_trigger_welcome_test", { status: 429, ms: Date.now() - t0 });
    return send429(res, rl, "admin_newsletter_trigger_welcome_test");
  }

  const body = await readJsonBody(req);
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!email || !EMAIL_RE.test(email)) {
    return res.status(400).json({ error: "invalid_email" });
  }
  const by = typeof body.by === "string" && EMAIL_RE.test(body.by.trim().toLowerCase())
    ? body.by.trim().toLowerCase()
    : null;
  // Default to forcing the re-send for admin tests. Operator can pass
  // `force: false` to actually exercise the idempotency path.
  const force = body.force === false ? false : true;

  const token = process.env.GITHUB_DISPATCH_TOKEN || "";
  if (!token) {
    logApi("admin.newsletter_trigger_welcome_test", {
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

  const baselineRunId = await getLatestRunId({ repo, workflowFile: WORKFLOW_FILE, token });

  let gh;
  try {
    gh = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pulpo-admin-newsletter-welcome-test",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          recipient_email: email,
          send_mode: "yes",
          source: "admin",
          force: force ? "yes" : "no",
        },
      }),
    });
  } catch (err) {
    logApi("admin.newsletter_trigger_welcome_test", {
      status: 502, ms: Date.now() - t0, reason: "github_fetch_failed",
      error: (err && err.message) || "(no message)",
    });
    await emitTriggerEvent({
      to: email, by, force,
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
    logApi("admin.newsletter_trigger_welcome_test", {
      status: gh.status, ms: Date.now() - t0, reason: "github_non_204",
    });
    await emitTriggerEvent({
      to: email, by, force,
      result: "error",
      detail: `github_status_${gh.status}: ${detail.slice(0, 200)}`,
    });
    return res.status(gh.status === 404 ? 404 : 502).json({
      error: "github_dispatch_rejected",
      github_status: gh.status,
      detail: detail.slice(0, 500),
    });
  }

  if (baselineRunId !== null) {
    const newRun = await pollForNewerRun({
      repo, workflowFile: WORKFLOW_FILE, token, baselineId: baselineRunId,
    });
    if (!newRun) {
      logApi("admin.newsletter_trigger_welcome_test", {
        status: 502, ms: Date.now() - t0, reason: "dispatch_accepted_but_no_run_created",
        baseline_run_id: baselineRunId,
      });
      await emitTriggerEvent({
        to: email, by, force,
        result: "error",
        detail: "dispatch_accepted_but_no_run_created: GitHub returned 204 but no workflow run appeared within poll window",
      });
      return res.status(502).json({
        error: "dispatch_accepted_but_no_run_created",
        hint: "GitHub accepted the dispatch but no workflow run materialized within ~8s. This is usually a transient GitHub Actions issue — retry in ~30s. If it persists, check https://www.githubstatus.com.",
      });
    }
    logApi("admin.newsletter_trigger_welcome_test", {
      status: 202, ms: Date.now() - t0,
      repo, ref, email_domain: email.split("@")[1] || "",
      run_id: newRun.id, verified: true, force,
    });
    await emitTriggerEvent({
      to: email, by, force,
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
      hint: "Welcome arrives in ~30–60s once the workflow finishes. Subject: 'Welcome to Pulpo Pro — your first 10'.",
    });
  }

  logApi("admin.newsletter_trigger_welcome_test", {
    status: 202, ms: Date.now() - t0,
    repo, ref, email_domain: email.split("@")[1] || "",
    verified: false, reason: "baseline_unavailable", force,
  });

  await emitTriggerEvent({
    to: email, by, force,
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
