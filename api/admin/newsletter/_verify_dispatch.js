// Shared helper: verify a `workflow_dispatch` POST actually queued a run.
//
// GitHub's `POST /repos/{owner}/{repo}/actions/workflows/{file}/dispatches`
// returns 204 once the dispatch payload is accepted. That 204 does NOT
// guarantee a workflow run was created — during transient GitHub Actions
// service hiccups the dispatch can be silently dropped (204 returned,
// no run materialises). This bit us in production on 2026-05-31: the
// admin widget showed "✓ Sent" for a preview to a real subscriber and
// the email never went out because no workflow ever ran.
//
// Usage: capture `baselineRunId` BEFORE dispatching, then call
// `pollForNewerRun` AFTER GitHub returns 204. If `pollForNewerRun`
// returns `null` after the timeout, the endpoint should treat the
// dispatch as failed and return 502 so the widget surfaces a real
// error instead of falsely logging success.
//
// Run IDs are monotonically increasing across the entire GitHub
// instance, so id > baseline is a tight invariant — no timestamp
// math, no clock-skew worries, no ambiguity when two operators
// dispatch within the same second.

const GH_HEADERS = (token) => ({
  "Authorization": `Bearer ${token}`,
  "Accept": "application/vnd.github+json",
  "X-GitHub-Api-Version": "2022-11-28",
  "User-Agent": "pulpo-admin-newsletter-verify",
});

// Returns the most recent workflow_dispatch run id for the given
// workflow file, or 0 when the workflow has no runs yet, or `null`
// when the GitHub API call fails. A `null` return signals "we cannot
// verify"; callers should treat that as a soft skip (return 202 with
// a warning flag) rather than fail closed.
async function getLatestRunId({ repo, workflowFile, token }) {
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflowFile}/runs?event=workflow_dispatch&per_page=1`;
  let r;
  try {
    r = await fetch(url, { headers: GH_HEADERS(token) });
  } catch {
    return null;
  }
  if (!r.ok) return null;
  const body = await r.json().catch(() => null);
  if (!body || !Array.isArray(body.workflow_runs)) return null;
  if (body.workflow_runs.length === 0) return 0;
  const first = body.workflow_runs[0];
  return typeof first.id === "number" ? first.id : null;
}

// Polls the workflow runs API until a run with id > baselineId
// appears, or the timeout elapses. Returns the new run object on
// success, or `null` on timeout. Per-attempt errors are swallowed so a
// single transient API hiccup mid-poll doesn't abort the whole loop.
//
// Default budget: 8s with 1s interval = up to 8 polls. Tuned to:
//   • Catch the common case (GitHub queues the run in 0.5–3s).
//   • Stay well under Vercel's 15s serverless function budget once you
//     add the upstream dispatch round-trip (~0.5s) and baseline GET
//     (~0.5s).
//   • Be cheap on GitHub API rate limits (5000/hour per token; this
//     uses at most ~10 calls per dispatch).
async function pollForNewerRun({
  repo,
  workflowFile,
  token,
  baselineId,
  timeoutMs = 8000,
  intervalMs = 1000,
}) {
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflowFile}/runs?event=workflow_dispatch&per_page=5`;
  const deadline = Date.now() + timeoutMs;
  const headers = GH_HEADERS(token);
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    let r;
    try {
      r = await fetch(url, { headers });
    } catch {
      continue;
    }
    if (!r.ok) continue;
    const body = await r.json().catch(() => null);
    if (!body || !Array.isArray(body.workflow_runs)) continue;
    const fresh = body.workflow_runs.find(
      (run) => typeof run.id === "number" && run.id > baselineId,
    );
    if (fresh) return fresh;
  }
  return null;
}

module.exports = { getLatestRunId, pollForNewerRun };
