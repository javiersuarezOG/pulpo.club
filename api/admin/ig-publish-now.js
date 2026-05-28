// POST /api/admin/ig-publish-now
//
// Body: { day: <int>, dry_run?: <bool> }
//
// Triggers the `pulpo-ig-publish` GitHub Actions workflow with
// force_day=<day>.  The workflow runs automation.ig_publish with
// --force-day, bypassing the scheduled_for gate so the operator can
// test-publish a specific queue item on the spot rather than waiting
// for its scheduled slot.
//
// What this does NOT bypass:
//   - IG_PAUSED kill switch
//   - approved=true gate (operator must approve via Submit batch first)
//   - posted_at non-null gate (already-published items stay published)
//
// Auth posture matches api/admin/newsletter/trigger-preview.js and
// api/admin/ig-queue-apply.js: no bearer; the real perimeter is
// GITHUB_DISPATCH_TOKEN (fine-grained PAT, actions:write only on this
// repo).  Worst-case abuse here: an attacker fires repeated test
// publishes against approved items.  Each one burns one IG API quota
// slot AND a paid CI run, so the rate limit is intentionally tight.
//
// Rate limit: 5 dispatches per IP per hour.  Each fires a publish that
// hits IG with a real carousel post — cheap insurance against a stuck
// button loop.

const { makeRateLimiter, send429, ipFromRequest } = require("../_rate_limit");

const DEFAULT_REPO = "javiersuarezOG/pulpo.club";
const DEFAULT_REF = "main";
const WORKFLOW_FILE = "ig-publish.yml";

const limiter = makeRateLimiter({
  windowMs: 60 * 60 * 1000,
  maxAttempts: 5,
  name: "admin_ig_publish_now",
});

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try {
    const chunks = [];
    for await (const chunk of req)
      chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
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
    logApi("admin.ig_publish_now", { status: 429, ms: Date.now() - t0 });
    return send429(res, rl, "admin_ig_publish_now");
  }

  const body = await readJsonBody(req);
  const day = Number(body.day);
  // 1..365 covers any plausible queue length.  A negative or NaN value
  // is almost always a typo / stale UI state.
  if (!Number.isInteger(day) || day < 1 || day > 365) {
    return res.status(400).json({
      error: "invalid_day",
      hint: "day must be a positive integer matching a queue item.",
    });
  }
  const dryRun = body.dry_run === true;

  const token = process.env.GITHUB_DISPATCH_TOKEN || "";
  if (!token) {
    logApi("admin.ig_publish_now", {
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
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pulpo-admin-ig-publish-now",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          force_day: String(day),
          dry_run: dryRun ? "true" : "false",
        },
      }),
    });
  } catch (err) {
    logApi("admin.ig_publish_now", {
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
    logApi("admin.ig_publish_now", {
      status: gh.status, ms: Date.now() - t0, reason: "github_non_204",
    });
    return res.status(gh.status === 404 ? 404 : 502).json({
      error: "github_dispatch_rejected",
      github_status: gh.status,
      detail: detail.slice(0, 500),
    });
  }

  logApi("admin.ig_publish_now", {
    status: 202, ms: Date.now() - t0,
    repo, ref, day, dry_run: dryRun,
  });

  return res.status(202).json({
    ok: true,
    repo,
    ref,
    workflow: WORKFLOW_FILE,
    day,
    dry_run: dryRun,
    runs_url: `https://github.com/${repo}/actions/workflows/${WORKFLOW_FILE}`,
    hint: "Workflow picks up the dispatch in ~5s; publish finishes in ~30-60s. Item is marked posted on success.",
  });
};
