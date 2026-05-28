// GET /api/admin/ig-queue
//
// Returns the current IG batch queue payload plus a computed `health`
// block for /admin/ig-review's dashboard tile.  Reads
// `web/data/ig_queue.json` (produced by automation/ig_queue_builder.py;
// see PR-3a #505) and forwards it untouched.  Empty state (queue file
// missing or empty) returns 200 with `{ queue: null, hint: "..." }` so
// the widget can show a "run the builder" call-to-action.
//
// `health` is computed server-side so the widget can render the dashboard
// tile from a single fetch:
//
//   {
//     ig_paused:          boolean,           // env IG_PAUSED == "1"
//     ig_user_id_set:     boolean,           // env IG_USER_ID present
//     ig_token_set:       boolean,           // env IG_ACCESS_TOKEN present
//     items_total:        number,
//     items_approved:     number,
//     items_pending:      number,
//     items_needs_human:  number,
//     items_posted:       number,
//     last_posted_at:     ISO | null,        // newest posted_at across items
//     last_posted_day:    number | null,
//     next_due:           { day, shelf, scheduled_for } | null,
//                                            // earliest approved & unposted
//     next_unapproved_due: { day, shelf, scheduled_for } | null,
//                                            // earliest unapproved & overdue (alert)
//     blockers:           [string]           // ordered list of human reasons
//                                            // shipping is currently blocked
//   }
//
// Auth: none, matching the precedent set by the newsletter trigger-preview
// endpoint.  The data is pre-publication captions + poster paths +
// listing IDs — non-sensitive at the catalogue level (no PII, no
// credentials).  Write mutations route through workflow_dispatch
// elsewhere.
//
// Defensive shape: every health field has a clean default, so the widget
// can render even against a half-broken queue file.

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

// ── health derivation ────────────────────────────────────────────────

function _trueBool(v) {
  if (v === true) return true;
  if (typeof v !== "string") return false;
  const s = v.trim().toLowerCase();
  return s === "1" || s === "true" || s === "yes" || s === "on";
}

function _parseISO(s) {
  if (!s || typeof s !== "string") return null;
  const d = new Date(s.replace("Z", "+00:00"));
  return Number.isFinite(d.getTime()) ? d : null;
}

function deriveHealth(payload) {
  // Defaults so the widget always has stable keys to read.
  const out = {
    ig_paused:           _trueBool(process.env.IG_PAUSED || ""),
    ig_user_id_set:      Boolean((process.env.IG_USER_ID || "").trim()),
    ig_token_set:        Boolean((process.env.IG_ACCESS_TOKEN || "").trim()),
    items_total:         0,
    items_approved:      0,
    items_pending:       0,
    items_needs_human:   0,
    items_posted:        0,
    last_posted_at:      null,
    last_posted_day:     null,
    next_due:            null,
    next_unapproved_due: null,
    blockers:            [],
  };

  const items = Array.isArray(payload && payload.items) ? payload.items : [];
  out.items_total = items.length;

  const now = Date.now();
  let bestNextDue = null;
  let bestUnapprovedOverdue = null;
  let latestPosted = null;

  for (const it of items) {
    if (it && it.approved === true) out.items_approved++;
    if (it && it.status === "pending") out.items_pending++;
    if (it && it.status === "needs_human") out.items_needs_human++;

    if (it && it.posted === true) {
      out.items_posted++;
      const pa = _parseISO(it.posted_at);
      if (pa && (!latestPosted || pa > latestPosted.at)) {
        latestPosted = { at: pa, day: it.day };
      }
    }

    const sched = _parseISO(it && it.scheduled_for);
    if (!sched) continue;

    if (it.approved === true && it.posted !== true) {
      if (!bestNextDue || sched < bestNextDue.at) {
        bestNextDue = {
          at:    sched,
          day:   it.day,
          shelf: it.shelf || null,
        };
      }
    }
    // Overdue + unapproved = the operator forgot to approve before the
    // scheduled time.  Surface this on the dashboard so a missed day
    // doesn't silently slip.
    if (it.approved !== true && it.posted !== true && sched.getTime() <= now) {
      if (!bestUnapprovedOverdue || sched < bestUnapprovedOverdue.at) {
        bestUnapprovedOverdue = {
          at:    sched,
          day:   it.day,
          shelf: it.shelf || null,
        };
      }
    }
  }

  if (latestPosted) {
    out.last_posted_at = latestPosted.at.toISOString();
    out.last_posted_day = latestPosted.day;
  }
  if (bestNextDue) {
    out.next_due = {
      day:           bestNextDue.day,
      shelf:         bestNextDue.shelf,
      scheduled_for: bestNextDue.at.toISOString(),
    };
  }
  if (bestUnapprovedOverdue) {
    out.next_unapproved_due = {
      day:           bestUnapprovedOverdue.day,
      shelf:         bestUnapprovedOverdue.shelf,
      scheduled_for: bestUnapprovedOverdue.at.toISOString(),
    };
  }

  // Ordered list of human-readable blockers.  The widget renders them
  // verbatim with severity styling.  Order: hardest blockers first.
  if (!out.ig_user_id_set || !out.ig_token_set) {
    out.blockers.push("Missing IG_USER_ID or IG_ACCESS_TOKEN secret — publisher will exit before any API call.");
  }
  if (out.ig_paused) {
    out.blockers.push("IG_PAUSED=1 — the cron skips every run. Set IG_PAUSED='' to resume.");
  }
  if (out.items_total === 0) {
    out.blockers.push("Queue is empty. Run automation/ig_queue_builder to populate.");
  }
  if (out.items_total > 0 && out.items_approved === 0) {
    out.blockers.push("Nothing approved. Edit ig_queue.json to set approved=true on items you want to ship.");
  }
  if (bestUnapprovedOverdue) {
    out.blockers.push(`D${bestUnapprovedOverdue.day} (${bestUnapprovedOverdue.shelf || "?"}) was scheduled for ${bestUnapprovedOverdue.at.toISOString()} but isn't approved.`);
  }
  return out;
}

module.exports = async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const lookup = readQueueFile();

  // Empty / missing state — return 200 with a hint, NOT 404.  The widget
  // renders an actionable empty state ("run the queue builder").  We
  // still emit a partial `health` block so the dashboard tile can show
  // "secrets configured: yes/no" + the empty-queue blocker.
  if (!lookup.found) {
    const health = deriveHealth({});  // no items; surface secret + queue-empty blockers
    logApi("admin.ig_queue", {
      status: 200, ms: Date.now() - t0, queue: "empty",
      reason: lookup.reason || "unknown",
    });
    return res.status(200).json({
      queue:  null,
      health,
      hint:   (
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

  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    logApi("admin.ig_queue", {
      status: 500, ms: Date.now() - t0, reason: "shape_invalid",
    });
    return res.status(500).json({
      error: "queue_shape_invalid",
      detail: "Expected object payload from automation/ig_queue_builder.py",
    });
  }

  const health = deriveHealth(payload);
  const itemCount = Array.isArray(payload.items) ? payload.items.length : 0;
  logApi("admin.ig_queue", {
    status: 200, ms: Date.now() - t0,
    items: itemCount, batch: payload.batch || "(unset)",
    approved: health.items_approved, paused: health.ig_paused,
  });

  res.setHeader("Cache-Control", "private, max-age=10");
  return res.status(200).json({ queue: payload, health });
};
