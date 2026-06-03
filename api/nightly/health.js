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
  featured: { json: null, mtime: 0 },
  photoContract: { json: null, mtime: 0 },
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

// PRD P2-1 — run_history.json is intentionally single-file across
// countries (per-country last_updated/ranked are split; the audit log
// stays unified). Operators looking at `last_7_runs` need country
// scoping so a PA scaffold run with total=20 doesn't get misread as an
// SV collapse from total=959.
//
// Resolution order per row:
//   1. row.country_code (stamped at write time going forward, see
//      automation/pipeline_steps.py:_append_run_history).
//   2. Heuristic from per_source_raw — keys ⊆ PA_ONLY_SOURCES → "PA";
//      anything else → "SV". The heuristic is intentionally conservative
//      so a partial SV run (encuentra24-only after a brownout) does not
//      flip identity. PA's scaffold runs only use encuentra24 today.
//
// PA_ONLY_SOURCES is a hardcoded set, not read from the country
// manifest, because the manifest doesn't list sources yet (PR-MC-PA-1
// shipped a minimum-viable scaffold; reference data lands in
// PR-MC-PA-2+). When the manifest gains a `sources` array, replace
// this set by reading the manifest.
const PA_ONLY_SOURCES = new Set(["encuentra24"]);

function inferCountry(row) {
  if (row && typeof row.country_code === "string") {
    const cc = row.country_code.toUpperCase();
    if (cc === "SV" || cc === "PA") return cc;
  }
  const per = row && typeof row.per_source_raw === "object" ? row.per_source_raw : null;
  if (!per) return "SV";
  const keys = Object.keys(per);
  if (keys.length === 0) return "SV";
  // PA only if every key is in the PA-only set AND the set is small
  // (single-key today — multi-source PA in the future will need the
  // manifest-driven solution above).
  if (keys.every((k) => PA_ONLY_SOURCES.has(k))) return "PA";
  return "SV";
}

function buildLast7Runs(runHistory, countryFilter = null) {
  if (!Array.isArray(runHistory)) return [];
  let rows = runHistory;
  if (countryFilter && countryFilter !== "all") {
    rows = rows.filter((r) => inferCountry(r) === countryFilter);
  }
  return rows
    .slice(-RUN_HISTORY_LIMIT)
    .map((r) => ({
      ts: r.ts ?? null,
      total: r.total ?? null,
      dropped: r.dropped ?? null,
      duration_s: r.duration ?? null,
      error_count: r.error_count ?? null,
      country_code: inferCountry(r),
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

// PRD P1-1 — surface featured.json freshness so a stale pick is
// detectable from /api/nightly/health without opening the file. Returns
// `null` when the file is missing (PA-only run, file-not-yet-generated)
// so dashboards can render an explicit "absent" rather than guessing.
function featuredFreshness(featured) {
  if (!featured || typeof featured !== "object") return null;
  const pickedAt = typeof featured.picked_at === "string" ? featured.picked_at : null;
  const expiresAt = typeof featured.expires_at === "string" ? featured.expires_at : null;
  const expiresMs = expiresAt ? Date.parse(expiresAt) : NaN;
  const fresh = Number.isFinite(expiresMs) ? expiresMs > Date.now() : false;
  return {
    picked_at: pickedAt,
    expires_at: expiresAt,
    fresh,
    age_hours: pickedAt ? Number((hoursSince(pickedAt) ?? 0).toFixed(2)) : null,
  };
}

// PRD P1-9 — surface brownout-state sources alongside the binary
// `failed_sources_last_run`. The Python nightly's
// scripts/check_source_health.py computes the authoritative state via
// pulpo.source_health.compute_brownout_states; this endpoint mirrors
// the calculation client-side from the same `source_health_history.jsonl`
// data so JS callers (admin/sources widget, ops dashboards) don't need
// a separate sidecar fetch.
//
// Thresholds:
//   green       — kept-count ≥ 90% of rolling 7-run median.
//   degraded    — kept-count < 50% of median for the latest run.
//   red         — kept-count < 50% of median for two+ consecutive runs.
//   recovering  — previous run was degraded/red AND current ratio
//                 sits in 50%-90% (climbing back).
const SRC_DEGRADED = 0.5;
const SRC_RECOVERING_CEIL = 0.9;
const SRC_ROLLING_WINDOW = 7;
const SRC_MIN_HISTORY = 3;

function _keptCount(row) {
  const raw = row && (row.kept != null ? row.kept : row.scraped);
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0;
}

function _median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function _statusToBrownout(status) {
  if (status === "green") return "green";
  if (status === "red") return "red";
  if (status === "skipped") return "skipped";
  return "unknown";
}

function degradedSources(rows) {
  if (!Array.isArray(rows)) return [];
  // Group by source, sort chronologically.
  const bySource = new Map();
  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    const src = r.source || "?";
    if (!bySource.has(src)) bySource.set(src, []);
    bySource.get(src).push(r);
  }

  const out = [];
  for (const [source, history] of bySource) {
    history.sort((a, b) => String(a.ts || "").localeCompare(String(b.ts || "")));
    if (!history.length) continue;
    const latest = history[history.length - 1];
    const latestCount = _keptCount(latest);
    const window = history.slice(-(SRC_ROLLING_WINDOW + 1), -1);
    const historical = window.map(_keptCount).filter((n) => n > 0);

    if (historical.length < SRC_MIN_HISTORY) continue;

    const median = _median(historical);
    const ratio = median > 0 ? latestCount / median : 0;
    const previousStatus = history.length > 1
      ? _statusToBrownout(history[history.length - 2].status)
      : null;

    // Walk back to count consecutive runs <50% of their own prior window.
    let consecutive = 0;
    for (let i = history.length - 1; i >= 0; i--) {
      const row = history[i];
      const count = _keptCount(row);
      const priorWindow = history
        .slice(Math.max(0, i - SRC_ROLLING_WINDOW), i)
        .map(_keptCount)
        .filter((n) => n > 0);
      if (priorWindow.length < SRC_MIN_HISTORY) break;
      const priorMedian = _median(priorWindow);
      const priorRatio = priorMedian > 0 ? count / priorMedian : 0;
      if (priorRatio < SRC_DEGRADED) consecutive += 1;
      else break;
    }

    let status;
    if (ratio < SRC_DEGRADED) {
      status = consecutive >= 2 ? "red" : "degraded";
    } else if (ratio < SRC_RECOVERING_CEIL
               && (previousStatus === "red" || previousStatus === "degraded")) {
      status = "recovering";
    } else {
      status = "green";
    }

    if (status === "green") continue;
    out.push({
      source,
      status,
      count: latestCount,
      rolling_median_7: Number(median.toFixed(2)),
      ratio: Number(ratio.toFixed(4)),
      consecutive_degraded_runs: consecutive,
      previous_status: previousStatus,
      failure_id: typeof latest.failure_id === "string" ? latest.failure_id : null,
      error_class: typeof latest.error_class === "string" ? latest.error_class : null,
    });
  }
  out.sort((a, b) => a.source.localeCompare(b.source));
  return out;
}

// PRD P1-2 — `web/data/photo_contract.json` is written by
// `pulpo.photo_contract.enforce_photo_contract` after every nightly.
// Surface the key fields so /api/nightly/health is the single
// observability surface for "do listings actually have a working photo
// today?". `null` when the sidecar is missing (legacy data, brand-new
// install) so callers can render "absent" explicitly.
function summarizePhotoContract(raw) {
  if (!raw || typeof raw !== "object") return null;
  const safeNum = (v) => (typeof v === "number" ? v : null);
  return {
    ranked_total: safeNum(raw.ranked_total),
    with_local_path: safeNum(raw.with_local_path),
    local_path_exists: safeNum(raw.local_path_exists),
    local_path_missing: safeNum(raw.local_path_missing),
    missing_rate: safeNum(raw.missing_rate),
    top_browse: raw.top_browse && typeof raw.top_browse === "object"
      ? {
        n: safeNum(raw.top_browse.n),
        present: safeNum(raw.top_browse.present),
        missing: safeNum(raw.top_browse.missing),
        coverage: safeNum(raw.top_browse.coverage),
      }
      : null,
    top_hero: raw.top_hero && typeof raw.top_hero === "object"
      ? {
        n: safeNum(raw.top_hero.n),
        present: safeNum(raw.top_hero.present),
        missing: safeNum(raw.top_hero.missing),
        coverage: safeNum(raw.top_hero.coverage),
      }
      : null,
    evaluated_at: typeof raw.evaluated_at === "string" ? raw.evaluated_at : null,
  };
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

// Default country from env (Vercel deploys set PULPO_ACTIVE_COUNTRY for
// the active manifest). Falls back to "SV" so localdev + tests don't
// require the env to be set.
function activeCountryFromEnv() {
  const raw = (process.env.PULPO_ACTIVE_COUNTRY || "SV").toUpperCase();
  return raw === "PA" ? "PA" : "SV";
}

// Resolve the country filter from request query. Accepts:
//   ?country=SV   → SV-only last_7_runs (default)
//   ?country=PA   → PA-only last_7_runs
//   ?country=all  → unfiltered (operators inspecting cross-country runs)
//   omitted       → active country from env
// Anything else falls back to active country.
function resolveCountryFilter(query) {
  if (!query || typeof query.country !== "string") return activeCountryFromEnv();
  const raw = query.country.toUpperCase();
  if (raw === "SV" || raw === "PA" || raw === "ALL") {
    return raw === "ALL" ? "all" : raw;
  }
  return activeCountryFromEnv();
}

function buildHealth(countryFilter = null) {
  const lastUpdated = loadJsonCached("lastUpdated", "last_updated.json");
  const runHistory = loadJsonCached("runHistory", "run_history.json");
  const vlmRows = loadJsonlCached("vlmBudget", "llm_vision_budget.jsonl");
  const sourceHealthRows = loadJsonlCached("sourceHealth", "source_health_history.jsonl");
  const featured = loadJsonCached("featured", "featured.json");
  const photoContract = loadJsonCached("photoContract", "photo_contract.json");

  const lastDataCommitAt = lastUpdated ? lastUpdated.last_updated ?? null : null;
  const lastTotalListings = lastUpdated ? lastUpdated.total_listings ?? null : null;
  const lastDurationS = lastUpdated ? lastUpdated.duration_seconds ?? null : null;

  const ageHours = hoursSince(lastDataCommitAt);
  const isStale = ageHours == null || ageHours > STALE_THRESHOLD_H;
  const filter = countryFilter ?? activeCountryFromEnv();

  return {
    status: isStale ? "stale" : "ok",
    country: filter,
    last_data_commit_at: lastDataCommitAt,
    last_data_commit_age_hours: ageHours == null ? null : Number(ageHours.toFixed(2)),
    last_run: {
      total_listings: lastTotalListings,
      dropped: lastUpdated ? lastUpdated.dropped ?? null : null,
      duration_s: lastDurationS,
    },
    last_7_runs: buildLast7Runs(runHistory, filter),
    failed_sources_last_run: failedSourcesLastRun(lastUpdated, sourceHealthRows),
    degraded_sources: degradedSources(sourceHealthRows),
    vlm_budget_today: vlmBudgetToday(vlmRows),
    featured: featuredFreshness(featured),
    photo_contract: summarizePhotoContract(photoContract),
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
    const filter = resolveCountryFilter(req && req.query);
    const body = buildHealth(filter);
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
  featuredFreshness,
  degradedSources,
  summarizePhotoContract,
  hoursSince,
  inferCountry,
  resolveCountryFilter,
  activeCountryFromEnv,
  STALE_THRESHOLD_H,
  VLM_DAILY_BUDGET_USD,
};
