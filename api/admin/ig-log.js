// GET /api/admin/ig-log?limit=50
//
// Returns the IG publisher's activity log — one entry per publish
// attempt (posted / failed) — newest first, for the admin console's
// activity feed.  Reads `web/data/ig_post_log.jsonl` (append-only,
// written by automation/ig_publish.py on every attempt and committed by
// the ig-publish workflow).
//
// Empty state (log file missing) returns 200 with `{ entries: [] }` —
// the console renders "nothing published yet", NOT an error.
//
// Auth: none, matching api/admin/ig-queue.js.  The log is non-sensitive
// (pre-published caption previews + media ids + error strings — no PII,
// no credentials).

const fs = require("fs");
const path = require("path");

// Two-candidate path resolution matches api/admin/ig-queue.js — Vercel's
// bundler relocates the function root depending on the build mode.
const PATH_CANDIDATES = [
  path.join(__dirname, "..", "..", "web", "data", "ig_post_log.jsonl"),
  path.join(process.cwd(), "web", "data", "ig_post_log.jsonl"),
];

const MAX_LIMIT = 200;
const DEFAULT_LIMIT = 50;

function readLogFile() {
  for (const p of PATH_CANDIDATES) {
    try {
      const text = fs.readFileSync(p, "utf8");
      return { found: true, text };
    } catch {
      continue;
    }
  }
  return { found: false, text: "" };
}

function logApi(name, fields) {
  const parts = ["[api]", name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

// Parse the jsonl defensively — a single malformed line must not blank
// the whole feed. Bad lines are skipped, not fatal.
function parseEntries(text) {
  const out = [];
  for (const line of text.split("\n")) {
    const s = line.trim();
    if (!s) continue;
    try {
      const e = JSON.parse(s);
      if (e && typeof e === "object") out.push(e);
    } catch {
      // skip malformed line
    }
  }
  return out;
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  let limit = Number(req.query && req.query.limit);
  if (!Number.isInteger(limit) || limit < 1) limit = DEFAULT_LIMIT;
  if (limit > MAX_LIMIT) limit = MAX_LIMIT;

  const lookup = readLogFile();
  if (!lookup.found) {
    logApi("admin.ig_log", { status: 200, ms: Date.now() - t0, entries: 0, empty: true });
    return res.status(200).json({ entries: [], total: 0 });
  }

  const all = parseEntries(lookup.text);
  // Newest first. Entries carry an ISO `ts`; sort by it, falling back to
  // file order (append order ≈ chronological) when ts is missing.
  all.sort((a, b) => String(b.ts || "").localeCompare(String(a.ts || "")));
  const entries = all.slice(0, limit);

  logApi("admin.ig_log", {
    status: 200, ms: Date.now() - t0, entries: entries.length, total: all.length,
  });
  res.setHeader("Cache-Control", "private, max-age=10");
  return res.status(200).json({ entries, total: all.length });
};
