// GET /api/admin/ig-queue
//
// Returns the current IG batch queue payload for /admin/ig-review.
// Reads `web/data/ig_queue.json` (produced by automation/ig_queue_builder.py;
// see PR-3a #505) and forwards it untouched.  Empty state (queue file
// missing or empty) returns 200 with `{ queue: null, hint: "..." }` so the
// widget can show a "run the builder" call-to-action instead of an error.
//
// Auth: none, matching the precedent set by the newsletter trigger-preview
// endpoint (api/admin/newsletter/trigger-preview.js).  The data here is
// pre-publication captions + poster paths + listing IDs — non-sensitive
// at the catalogue level (no PII, no credentials).  Bearer-token auth
// kept blocking the operator on every iteration in the newsletter case
// and we don't want to repeat that cost for read-only review.  Write
// mutations (approve / skip) will route through GitHub workflow_dispatch
// in PR-4 and the dispatch token (GITHUB_DISPATCH_TOKEN) is the real
// security perimeter.
//
// Why a Vercel function and not a static file served from /data/: keeps
// the widget's data contract under a single owned URL so we can add
// auth, filtering, or denormalisation later without rebuilding the
// frontend deploy.  And the queue can legitimately be missing on a
// fresh repo before the first build — the function turns that into a
// clean 200 with hint rather than the static 404 a missing /data/*.json
// file would produce.

const fs = require("fs");
const path = require("path");

// Two-candidate path resolution matches api/social/listings.js — Vercel's
// serverless bundler relocates the function root depending on whether
// the build uses node-mod-server or vercel.json includeFiles.
const PATH_CANDIDATES = [
  path.join(__dirname, "..", "..", "web", "data", "ig_queue.json"),
  path.join(process.cwd(), "web", "data", "ig_queue.json"),
];

function readQueueFile() {
  let lastErr = null;
  for (const p of PATH_CANDIDATES) {
    try {
      const text = fs.readFileSync(p, "utf8");
      if (!text || !text.trim()) {
        return { found: false, reason: "empty_file", path: p };
      }
      return { found: true, text, path: p };
    } catch (err) {
      lastErr = err;
      continue;
    }
  }
  return { found: false, reason: "not_found", error: lastErr };
}

function logApi(name, fields) {
  const parts = ["[api]", name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

module.exports = async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const lookup = readQueueFile();

  // Empty / missing state — return 200 with a hint, NOT 404.  The admin
  // widget renders an actionable empty state ("run the queue builder")
  // rather than a generic error.
  if (!lookup.found) {
    logApi("admin.ig_queue", {
      status: 200, ms: Date.now() - t0, queue: "empty",
      reason: lookup.reason || "unknown",
    });
    return res.status(200).json({
      queue: null,
      hint: (
        "ig_queue.json not found in web/data/. Run the builder: " +
        "`python3 -m automation.ig_queue_builder` (after the nightly's " +
        "ig_candidates.json is committed)."
      ),
    });
  }

  let payload;
  try {
    payload = JSON.parse(lookup.text);
  } catch (err) {
    logApi("admin.ig_queue", {
      status: 500, ms: Date.now() - t0, reason: "parse_error",
    });
    return res.status(500).json({
      error: "queue_parse_error",
      detail: (err && err.message) || "(no message)",
    });
  }

  // Defensive: payload should be the object the queue builder produced.
  // A non-object (e.g. someone hand-edited it to a list) would crash
  // the widget — turn it into a clean 500 instead.
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    logApi("admin.ig_queue", {
      status: 500, ms: Date.now() - t0, reason: "shape_invalid",
    });
    return res.status(500).json({
      error: "queue_shape_invalid",
      detail: "Expected object payload from automation/ig_queue_builder.py",
    });
  }

  const itemCount = Array.isArray(payload.items) ? payload.items.length : 0;
  logApi("admin.ig_queue", {
    status: 200, ms: Date.now() - t0,
    items: itemCount, batch: payload.batch || "(unset)",
  });

  // Short cache: the admin loads this on every page view.  10 seconds is
  // long enough to dedupe a tab refresh, short enough to see a fresh
  // build moments after the queue builder commits.
  res.setHeader("Cache-Control", "private, max-age=10");
  return res.status(200).json({ queue: payload });
};
