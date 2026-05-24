// SourcesHealthWidget — at-a-glance per-scraper health for the /admin hub.
//
// Reads ``web/data/source_health_history.jsonl`` (the JSONL appended at the
// end of every nightly run by ``automation/run.py::phase_normalize``). Each
// row is one source for one nightly:
//   { ts, source, status: "green"|"red", count, duration_s,
//     error_class, error_msg, failure_id, max_pages_hit, limit_hit }
//
// Auto-integration of new sources
// -------------------------------
// This widget groups rows by the ``source`` field — any slug that
// appears in the JSONL renders automatically with no widget code
// changes. The chain that makes that work:
//
//   1. New scraper at ``pulpo/scrapers/<slug>.py`` (calls register()).
//   2. Slug appended to ``PULPO_SOURCES`` in the nightly workflow.
//   3. Nightly writes a row for the new source to the JSONL.
//   4. This widget picks it up on next refresh.
//
// The chain has a load-bearing assumption — that the new slug is wired
// end-to-end. ``tests/test_source_integration.py`` is the deployment
// guard: it parses PULPO_SOURCES and fails CI if any declared source is
// missing the scraper module, test file, or runtime registration. So
// "shipping a new source" can't accidentally leave the dashboard blind.
//
// The widget surfaces:
//   - current status pill (green / red) per source
//   - latest nightly count + duration
//   - 14-day sparkline of counts (tiny inline SVG, no chart lib)
//   - last successful run timestamp (when currently red)
//   - last error message (truncated) + a deep link to the diagnostic
//     snapshot under web/data/scraper_failures/ when a failure_id is set
//
// Why fetch the JSONL directly instead of /api/nightly/health:
//   The health endpoint summarises only the *failed* sources of the
//   latest run. This widget wants every source, every recent run — so
//   parsing the JSONL client-side is the cleanest fit. The file is
//   tiny (~30KB after 30 days × 8 sources) so the runtime cost is
//   negligible.

import React, { useCallback, useEffect, useMemo, useState } from "react";

// ── styling ───────────────────────────────────────────────────────────
// Single <style> block keeps this widget self-contained — no global CSS
// changes needed. All colours/font/spacing come from existing tokens
// in web/app/styles/tokens.css (no off-token literals).
const STYLES = `
.sw-host { color: var(--ink); font-family: var(--font-sans); }

.sw-meta {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  color: var(--ink-3);
  margin: 0 0 16px;
  flex-wrap: wrap;
}
.sw-meta strong { color: var(--ink-2); font-weight: 500; }

.sw-refresh {
  background: none;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 4px 10px;
  font: inherit;
  font-size: 12px;
  color: var(--ink-2);
  cursor: pointer;
}
.sw-refresh:hover { border-color: var(--accent); color: var(--accent); }
.sw-refresh:disabled { opacity: 0.5; cursor: progress; }

.sw-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

.sw-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--paper);
}
@media (min-width: 720px) {
  .sw-row {
    grid-template-columns: 1.4fr 0.9fr 1.6fr 1fr;
    align-items: center;
    gap: 16px;
  }
}

.sw-source {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 15px;
  color: var(--ink);
  min-width: 0;
}
.sw-source code {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
}

.sw-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.sw-pill[data-status="green"]   { background: color-mix(in oklch, var(--badge-new) 18%, transparent); color: var(--badge-new); }
.sw-pill[data-status="red"]     { background: color-mix(in oklch, var(--badge-drop) 18%, transparent); color: var(--badge-drop); }
.sw-pill[data-status="unknown"] { background: var(--paper-2); color: var(--ink-3); }
.sw-pill .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: currentColor;
}

.sw-counts {
  font-size: 13px;
  color: var(--ink-2);
  line-height: 18px;
}
.sw-counts .big {
  font-family: var(--font-sans);
  font-size: 20px;
  line-height: 24px;
  font-weight: 600;
  color: var(--ink);
}
.sw-counts .delta-up   { color: var(--badge-new); margin-left: 4px; font-size: 12px; }
.sw-counts .delta-down { color: var(--badge-drop); margin-left: 4px; font-size: 12px; }
.sw-counts .sub {
  font-size: 11px;
  color: var(--ink-3);
  font-family: var(--font-mono);
}

.sw-trend {
  min-width: 0;
}
.sw-trend svg {
  display: block;
  width: 100%;
  height: 36px;
}
.sw-trend .axis {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-3);
  margin-top: 2px;
  display: flex;
  justify-content: space-between;
}

.sw-tail {
  font-size: 12px;
  color: var(--ink-3);
  line-height: 16px;
  min-width: 0;
}
.sw-tail .label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin-right: 6px;
}
.sw-tail .err {
  display: block;
  margin-top: 2px;
  color: var(--badge-drop);
  word-break: break-word;
}
.sw-tail a {
  color: var(--accent);
  text-decoration: none;
  font-family: var(--font-mono);
  font-size: 11px;
}
.sw-tail a:hover { text-decoration: underline; }

.sw-empty, .sw-error {
  border: 1px dashed var(--line-2);
  border-radius: 10px;
  padding: 24px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}
.sw-error { color: var(--badge-drop); border-color: var(--badge-drop); }
.sw-loading {
  font-size: 13px;
  color: var(--ink-3);
  padding: 16px 0;
}

/* Mobile labels for the desktop column heads — visible only inside each
   row card, so the small-screen layout reads "Status: green" instead of
   floating values without context. */
.sw-row .col-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin-right: 8px;
}
@media (min-width: 720px) { .sw-row .col-label { display: none; } }
`;

// ── data layer ────────────────────────────────────────────────────────

const HISTORY_PATH = "/data/source_health_history.jsonl";
// Sparkline window — 14 days is enough to spot a creeping decline
// without making the row tall. Keep in lockstep with the y-axis cap
// rounding below.
const SPARK_WINDOW_DAYS = 14;

function parseJsonl(text) {
  const out = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    try {
      out.push(JSON.parse(line));
    } catch (_) {
      // Skip malformed line; rest of the file is still valid.
    }
  }
  return out;
}

// Group rows by source, keep newest-first per source.
function groupBySource(rows) {
  const by = new Map();
  for (const r of rows) {
    if (!r || !r.source) continue;
    let arr = by.get(r.source);
    if (!arr) {
      arr = [];
      by.set(r.source, arr);
    }
    arr.push(r);
  }
  for (const arr of by.values()) {
    arr.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));
  }
  return by;
}

function lastGreenTs(rows) {
  for (const r of rows) {
    if (r.status === "green") return r.ts;
  }
  return null;
}

function formatRelative(iso) {
  if (!iso) return "—";
  const ms = Date.now() - Date.parse(iso);
  if (!Number.isFinite(ms)) return iso;
  const hours = ms / 3_600_000;
  if (hours < 1) return `${Math.max(1, Math.round(ms / 60_000))}m ago`;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function formatDuration(s) {
  if (s == null || !Number.isFinite(s)) return "—";
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return `${m}m${r.toString().padStart(2, "0")}s`;
}

// Build sparkline points from the most recent N rows. We invert the y
// so higher counts render visually higher (SVG y grows downward).
function buildSparkPath(rows, width = 120, height = 28) {
  if (!rows || rows.length === 0) return { d: "", points: [] };
  const window = rows.slice(0, SPARK_WINDOW_DAYS).reverse(); // oldest → newest
  const max = Math.max(1, ...window.map((r) => r.count || 0));
  const stepX = window.length > 1 ? width / (window.length - 1) : 0;
  const points = window.map((r, i) => {
    const x = i * stepX;
    const y = height - ((r.count || 0) / max) * (height - 2) - 1; // 1px padding
    return { x, y, count: r.count || 0, status: r.status, ts: r.ts };
  });
  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(" ");
  return { d, points, max };
}

// ── component ─────────────────────────────────────────────────────────

export function SourcesHealthWidget() {
  const [state, setState] = useState({
    status: "loading",        // loading | ready | error
    rows: [],
    fetchedAt: null,
    error: null,
  });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, status: "loading", error: null }));
    try {
      // Cache-buster on manual refresh so we see freshly-committed nightly
      // data without a hard reload.
      const url = `${HISTORY_PATH}?t=${Date.now()}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const text = await r.text();
      setState({
        status: "ready",
        rows: parseJsonl(text),
        fetchedAt: new Date().toISOString(),
        error: null,
      });
    } catch (e) {
      setState({
        status: "error",
        rows: [],
        fetchedAt: null,
        error: e && e.message ? e.message : "fetch failed",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(() => groupBySource(state.rows), [state.rows]);
  // Order: red first (oldest red goes top so the most-stuck source is
  // most visible), then green sorted by count descending so the biggest
  // healthy producers are above the trickle sources.
  const sources = useMemo(() => {
    const entries = Array.from(grouped.entries()).map(([source, rows]) => {
      const latest = rows[0] || {};
      return {
        source,
        rows,
        latest,
        isRed: latest.status === "red",
        latestCount: latest.count ?? 0,
        lastGreen: latest.status === "red" ? lastGreenTs(rows) : latest.ts,
      };
    });
    entries.sort((a, b) => {
      if (a.isRed !== b.isRed) return a.isRed ? -1 : 1;
      if (a.isRed && b.isRed) {
        // Older lastGreen = more stuck → higher in the list.
        const aT = a.lastGreen ? Date.parse(a.lastGreen) : 0;
        const bT = b.lastGreen ? Date.parse(b.lastGreen) : 0;
        return aT - bT;
      }
      return b.latestCount - a.latestCount;
    });
    return entries;
  }, [grouped]);

  return (
    <div className="sw-host">
      <style>{STYLES}</style>

      <div className="sw-meta">
        <span>
          Reads <strong>web/data/source_health_history.jsonl</strong>. One row per source per nightly.
          {state.fetchedAt && (
            <> Refreshed <strong>{formatRelative(state.fetchedAt)}</strong>.</>
          )}
        </span>
        <button
          type="button"
          className="sw-refresh"
          onClick={() => void load()}
          disabled={state.status === "loading"}
        >
          {state.status === "loading" ? "Loading…" : "Refresh"}
        </button>
      </div>

      {state.status === "error" && (
        <div className="sw-error">
          Couldn’t load source health: {state.error}
        </div>
      )}

      {state.status === "loading" && sources.length === 0 && (
        <div className="sw-loading">Loading…</div>
      )}

      {state.status === "ready" && sources.length === 0 && (
        <div className="sw-empty">
          No source health rows yet. The first nightly after Phase 0+1 will populate this.
        </div>
      )}

      {sources.length > 0 && (
        <div className="sw-list" role="list">
          {sources.map((entry) => (
            <SourceRow key={entry.source} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}

function SourceRow({ entry }) {
  const { source, rows, latest, isRed, lastGreen } = entry;
  const status = latest.status || "unknown";
  const count = latest.count ?? 0;
  const prev = rows[1] || null;
  const delta = prev ? count - (prev.count ?? 0) : 0;

  const { d, points } = useMemo(() => buildSparkPath(rows), [rows]);
  const strokeColor =
    status === "red"   ? "var(--badge-drop)" :
    status === "green" ? "var(--badge-new)"  :
                         "var(--ink-3)";

  // Latest snapshot link — falls back to the failures directory listing
  // (anchor still useful even if we don't know the exact filename).
  const snapshotHref = latest.failure_id
    ? `/data/scraper_failures/${source}_${(latest.ts || "").replaceAll(":", "-")}_${latest.failure_id}.json`
    : null;

  return (
    <div className="sw-row" role="listitem" aria-label={`${source} ${status}`}>
      {/* col 1 — source name + pill */}
      <div className="sw-source">
        <code>{source}</code>
        <span className="sw-pill" data-status={status}>
          <span className="dot" /> {status}
        </span>
      </div>

      {/* col 2 — count + delta + duration */}
      <div className="sw-counts">
        <span className="col-label">Last run</span>
        <span className="big">{count}</span>
        {prev && delta !== 0 && (
          <span className={delta > 0 ? "delta-up" : "delta-down"}>
            {delta > 0 ? `+${delta}` : delta}
          </span>
        )}
        <div className="sub">
          {formatDuration(latest.duration_s)} · {formatRelative(latest.ts)}
        </div>
      </div>

      {/* col 3 — sparkline */}
      <div className="sw-trend" aria-hidden="true">
        {points.length > 0 ? (
          <svg viewBox="0 0 120 36" preserveAspectRatio="none">
            <path
              d={d}
              fill="none"
              stroke={strokeColor}
              strokeWidth="1.4"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {points.map((p, i) => (
              <circle
                key={i}
                cx={p.x}
                cy={p.y}
                r={p.status === "red" ? 2 : 1.4}
                fill={p.status === "red" ? "var(--badge-drop)" : strokeColor}
              />
            ))}
          </svg>
        ) : (
          <span className="sub">no history</span>
        )}
        <div className="axis">
          <span>{SPARK_WINDOW_DAYS}d ago</span>
          <span>today</span>
        </div>
      </div>

      {/* col 4 — last-good + last-error */}
      <div className="sw-tail">
        {isRed ? (
          <>
            <span className="col-label">Last good</span>
            <span>{lastGreen ? formatRelative(lastGreen) : "—"}</span>
            {(latest.error_class || latest.error_msg) && (
              <span className="err">
                {latest.error_class && <strong>{latest.error_class}</strong>}
                {latest.error_class && latest.error_msg ? " — " : ""}
                {latest.error_msg && (latest.error_msg.length > 120
                  ? latest.error_msg.slice(0, 120) + "…"
                  : latest.error_msg)}
              </span>
            )}
            {snapshotHref && (
              <>
                <br />
                <a href={snapshotHref} target="_blank" rel="noreferrer">snapshot ↗</a>
              </>
            )}
          </>
        ) : (
          <>
            <span className="col-label">Healthy</span>
            <span>green {SPARK_WINDOW_DAYS}-day window</span>
          </>
        )}
      </div>
    </div>
  );
}
