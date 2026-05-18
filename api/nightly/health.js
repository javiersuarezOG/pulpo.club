// GET /api/nightly/health — public observability of the nightly pipeline.
//
// Reads existing sidecars in web/data/:
//   - last_updated.json           (last successful data commit)
//   - run_history.json            (per-run summary, last N runs)
//   - llm_vision_budget.jsonl     (booster spend + success rate)
//   - source_health_history.jsonl (per-source last-OK + error breakdown)
//
// Returns 503 when last_data_commit_at is older than STALE_THRESHOLD_H hours
// (default 36 h — gives the daily cron one missed run of slack before it
// reports unhealthy).
//
// Used by pulpo-social /healthz upstream-proxy field, and by humans
// debugging "did the nightly run last night?" — fastest possible answer
// without opening GH Actions.
//
// Companion to /api/social/listings.js. Same Vercel-serverless pattern,
// same in-process JSON cache keyed on mtime.

const fs = require("fs");
const path = require("path");

const STALE_THRESHOLD_H = 36;
const VLM_DAILY_BUDGET_USD = 1.0;
const RUN_HISTORY_LIMIT = 7;

const cache = {
  ranked: { json: null, mtime: 0 },
  lastUpdated: { json: null, mtime: 0 },
  runHistory: { json: null, mtime: 0 },
  vlmBudget: { rows: null, mtime: 0 },
  sourceHealth: { rows: null, mtime: 0 },
};

function resolveDataPath(filename) {
  const candidates = [
    path.join(__dirname, "..", "..", "web", "data", filename),
    path.join(process.cwd(), "web", "data", filename),
  ];
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) return p;
    } catch (_) {}
  }
  return null;
}

function loadJsonCached(slot, filename) {
  const p = resolveDataPath(filename);
  if (!p) return null;
  try {
    const stat = fs.statSync(p);
    const entry = cache[slot];
    if (entry.json && entry.mtime === stat.mtimeMs) return entry.json;
    const text = fs.readFileSync(p, "utf8");
    const parsed = JSON.parse(text);
    cache[slot] = { json: parsed, mtime: stat.mtimeMs };
    return parsed;
  } catch (_) {
    return null;
  }
}

function loadJsonlCached(slot, filename) {
  const p = resolveDataPath(filename);
  if (!p) return null;
  try {
    const stat = fs.statSync(p);
    const entry = cache[slot];
    if (entry.rows && entry.mtime === stat.mtimeMs) return entry.rows;
    const text = fs.readFileSync(p, "utf8");
    const rows = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      try {
        rows.push(JSON.parse(trimmed));
      } catch (_) {
        // Skip malformed line — don't fail the whole endpoint.
      }
    }
    cache[slot] = { rows, mtime: stat.mtimeMs };
    return rows;
  } catch (_) {
    return null;
  }
}

function hoursSince(isoString) {
  if (!isoString) return null;
  const t = Date.parse(isoString);
  if (!Number.isFinite(t)) return null;
  return (Date.now() - t) / 3_600_000;
}

function buildLast7Runs(runHistory) {
  if (!Array.isArray(runHistory)) return [];
  return runHistory
    .slice(-RUN_HISTORY_LIMIT)
    .map((r) => ({
      ts: r.ts ?? null,
      total: r.total ?? null,
      dropped: r.dropped ?? null,
      duration_s: r.duration ?? null,
      error_count: r.error_count ?? null,
    }))
    .reverse();
}

function failedSourcesLastRun(lastUpdated, sourceHealthRows) {
  // Primary: source_status block in last_updated.json (status per source).
  const status = lastUpdated && typeof lastUpdated.source_status === "object"
    ? lastUpdated.source_status
    : null;
  if (!status) return [];
  const lastTs = lastUpdated && lastUpdated.started_at ? lastUpdated.started_at : null;
  const failures = [];
  for (const [source, st] of Object.entries(status)) {
    if (st === "green") continue;
    let lastOkAt = null;
    let errorMsg = null;
    if (Array.isArray(sourceHealthRows)) {
      // Walk newest-first to find the last "green" ts for this source.
      for (let i = sourceHealthRows.length - 1; i >= 0; i--) {
        const row = sourceHealthRows[i];
        if (row.source !== source) continue;
        if (row.status === "green" && lastOkAt == null) {
          lastOkAt = row.ts;
        }
        if (errorMsg == null && row.ts === lastTs && row.error_msg) {
          errorMsg = row.error_msg;
        }
        if (lastOkAt && errorMsg) break;
      }
    }
    failures.push({ source, status: st, last_ok_at: lastOkAt, error: errorMsg });
  }
  return failures;
}

function vlmBudgetToday(rows) {
  if (!Array.isArray(rows)) {
    return { spend_usd: 0, pct_used: 0, success_rate_24h: null, call_count_24h: 0 };
  }
  const today = new Date().toISOString().slice(0, 10);
  const cutoffMs = Date.now() - 24 * 3_600_000;
  let spendToday = 0;
  let succ24 = 0;
  let fail24 = 0;
  for (const r of rows) {
    if (r.date === today && r.event === "llm_vision_call" && typeof r.cost_usd === "number") {
      spendToday += r.cost_usd;
    }
    const ts = r.ts ? Date.parse(r.ts) : null;
    if (Number.isFinite(ts) && ts >= cutoffMs) {
      if (r.event === "llm_vision_call") succ24 += 1;
      else if (r.event === "llm_vision_call_failed") fail24 += 1;
    }
  }
  const total24 = succ24 + fail24;
  return {
    spend_usd: Number(spendToday.toFixed(4)),
    pct_used: Number((spendToday / VLM_DAILY_BUDGET_USD).toFixed(3)),
    success_rate_24h: total24 === 0 ? null : Number((succ24 / total24).toFixed(3)),
    call_count_24h: total24,
  };
}

function buildHealth() {
  const lastUpdated = loadJsonCached("lastUpdated", "last_updated.json");
  const runHistory = loadJsonCached("runHistory", "run_history.json");
  const vlmRows = loadJsonlCached("vlmBudget", "llm_vision_budget.jsonl");
  const sourceHealthRows = loadJsonlCached("sourceHealth", "source_health_history.jsonl");

  const lastDataCommitAt = lastUpdated ? lastUpdated.last_updated ?? null : null;
  const lastTotalListings = lastUpdated ? lastUpdated.total_listings ?? null : null;
  const lastDurationS = lastUpdated ? lastUpdated.duration_seconds ?? null : null;

  const ageHours = hoursSince(lastDataCommitAt);
  const isStale = ageHours == null || ageHours > STALE_THRESHOLD_H;

  return {
    status: isStale ? "stale" : "ok",
    last_data_commit_at: lastDataCommitAt,
    last_data_commit_age_hours: ageHours == null ? null : Number(ageHours.toFixed(2)),
    last_run: {
      total_listings: lastTotalListings,
      dropped: lastUpdated ? lastUpdated.dropped ?? null : null,
      duration_s: lastDurationS,
    },
    last_7_runs: buildLast7Runs(runHistory),
    failed_sources_last_run: failedSourcesLastRun(lastUpdated, sourceHealthRows),
    vlm_budget_today: vlmBudgetToday(vlmRows),
    // Phase A follow-on (separate PR) will populate these from
    // nightly_progress.json + phase_durations.jsonl.
    current_progress: null,
    phase_durations: null,
    config: {
      stale_threshold_hours: STALE_THRESHOLD_H,
      vlm_daily_budget_usd: VLM_DAILY_BUDGET_USD,
      run_history_window: RUN_HISTORY_LIMIT,
    },
  };
}

module.exports = async (req, res) => {
  try {
    const body = buildHealth();
    const httpStatus = body.status === "stale" ? 503 : 200;
    res.setHeader("Cache-Control", "public, max-age=60");
    return res.status(httpStatus).json(body);
  } catch (err) {
    return res.status(500).json({
      status: "error",
      error: "internal_error",
      message: err && err.message ? err.message : String(err),
    });
  }
};

// Export pure helpers for unit testing without an HTTP layer.
module.exports.__testing__ = {
  buildHealth,
  buildLast7Runs,
  failedSourcesLastRun,
  vlmBudgetToday,
  hoursSince,
  STALE_THRESHOLD_H,
  VLM_DAILY_BUDGET_USD,
};
