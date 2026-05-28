// POST /api/admin/ig-queue-apply
//
// Body: { batch: "drop_01", decisions: { "1": "approve", "2": "skip", ... } }
//
// Triggers the `pulpo-ig-queue-apply` GitHub Actions workflow with
// `batch` + `decisions_json` inputs.  The workflow runs
// automation/ig_queue_apply.py against web/data/ig_queue.json on main
// and commits the mutation back via pulpo-bot.
//
// Why a workflow dispatch and not a direct write from this function:
// the queue lives in git, not a database, and the only credentialed
// write path to main is the bot PAT inside Actions.  Reusing the same
// channel keeps a single source of truth + a single audit trail.
//
// Auth: deliberately none beyond rate-limiting.  The real security
// perimeter is the GitHub PAT (`GITHUB_DISPATCH_TOKEN`, fine-grained,
// scoped `actions:write` on this repo only — cannot trigger arbitrary
// workflows or read anything).  Same posture as
// api/admin/newsletter/trigger-preview.js; admin auth was removed
// after env-var-not-deployed friction kept blocking the operator.
// Worst-case abuse here: an attacker spams approve/skip decisions
// against the current batch, which the operator notices on the next
// /admin/ig-review render and undoes with a counter-submit.  The
// publisher itself is rate-limited (one item/hour) so even a
// successful spam can't burn through the queue.
//
// Rate limit: 10 submits per IP per hour.  Each submit triggers a CI
// run + a git commit; 10/hr is plenty for a human operator and
// cheap insurance against a stuck Submit-button loop.

const { makeRateLimiter, send429, ipFromRequest } = require("../_rate_limit");

const VALID_DECISIONS = new Set(["approve", "skip"]);
const BATCH_RE = /^[a-z0-9_-]{1,32}$/;
const MAX_DECISIONS = 64; // 14-day batches today; cap protects against pathological input
const DEFAULT_REPO = "javiersuarezOG/pulpo.club";
const DEFAULT_REF = "main";
const WORKFLOW_FILE = "ig-queue-apply.yml";

const limiter = makeRateLimiter({
  windowMs: 60 * 60 * 1000,
  maxAttempts: 10,
  name: "admin_ig_queue_apply",
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

// Normalize the decisions object into a clean {dayString: "approve"|"skip"}
// map. Returns { ok: true, normalized } or { ok: false, error }.
// We validate aggressively here so the workflow never has to deal with
// malformed input — the workflow is the slow, expensive path.
function validateDecisions(decisions) {
  if (!decisions || typeof decisions !== "object" || Array.isArray(decisions)) {
    return { ok: false, error: "decisions must be an object" };
  }
  const entries = Object.entries(decisions);
  if (entries.length === 0) {
    return { ok: false, error: "decisions is empty" };
  }
  if (entries.length > MAX_DECISIONS) {
    return { ok: false, error: `decisions count exceeds ${MAX_DECISIONS}` };
  }
  const normalized = {};
  for (const [k, v] of entries) {
    const day = Number(k);
    if (!Number.isInteger(day) || day < 1 || day > 365) {
      return { ok: false, error: `decision key ${JSON.stringify(k)} is not a valid day` };
    }
    if (!VALID_DECISIONS.has(v)) {
      return {
        ok: false,
        error: `decision for day ${day} is ${JSON.stringify(v)}; expected approve|skip`,
      };
    }
    normalized[String(day)] = v;
  }
  return { ok: true, normalized };
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    logApi("admin.ig_queue_apply", { status: 429, ms: Date.now() - t0 });
    return send429(res, rl, "admin_ig_queue_apply");
  }

  const body = await readJsonBody(req);
  const batch = typeof body.batch === "string" ? body.batch.trim() : "";
  if (!batch || !BATCH_RE.test(batch)) {
    return res.status(400).json({
      error: "invalid_batch",
      hint: "batch must match /^[a-z0-9_-]{1,32}$/ (e.g. drop_01)",
    });
  }

  const v = validateDecisions(body.decisions);
  if (!v.ok) {
    return res.status(400).json({ error: "invalid_decisions", detail: v.error });
  }
  const decisions = v.normalized;

  const token = process.env.GITHUB_DISPATCH_TOKEN || "";
  if (!token) {
    logApi("admin.ig_queue_apply", {
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
        "User-Agent": "pulpo-admin-ig-queue-apply",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          batch,
          decisions_json: JSON.stringify(decisions),
        },
      }),
    });
  } catch (err) {
    logApi("admin.ig_queue_apply", {
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
    logApi("admin.ig_queue_apply", {
      status: gh.status, ms: Date.now() - t0, reason: "github_non_204",
    });
    return res.status(gh.status === 404 ? 404 : 502).json({
      error: "github_dispatch_rejected",
      github_status: gh.status,
      detail: detail.slice(0, 500),
    });
  }

  const counts = { approve: 0, skip: 0 };
  for (const v of Object.values(decisions)) counts[v]++;

  logApi("admin.ig_queue_apply", {
    status: 202, ms: Date.now() - t0,
    repo, ref, batch,
    approve: counts.approve, skip: counts.skip,
  });

  return res.status(202).json({
    ok: true,
    repo,
    ref,
    workflow: WORKFLOW_FILE,
    batch,
    counts,
    runs_url: `https://github.com/${repo}/actions/workflows/${WORKFLOW_FILE}`,
    hint: "Workflow picks up the dispatch in ~5s; commit lands on main in ~30s. Refresh the widget to see updated state.",
  });
};
