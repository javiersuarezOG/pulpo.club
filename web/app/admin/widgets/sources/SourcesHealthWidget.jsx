// SourcesHealthWidget — at-a-glance per-scraper health for the /admin hub.
//
// Three sections, all from data the nightly already commits:
//
//   1. Nightly status strip — last-run timestamp, duration, total
//      listings, overall green/red. Reads /data/last_updated.json.
//
//   2. Supply mix card — two side-by-side pies (geography + type)
//      computed across every listing in /data/ranked.list.json. This is
//      the "where are the gaps?" view: a tiny condo slice means thin
//      condo inventory, a tiny lake slice means lake under-supply,
//      and so on.
//
//   3. Per-source rows — name, status pill, listing count, two TINY
//      versions of the same pies scoped to that source. Spots
//      single-source dependencies ("if remax goes red we lose X% of
//      our condos"). For red sources, the per-source pies are
//      replaced with a "fix → see issue ↗" link that opens the
//      watchdog issue for the source (where the Phase-4 shadow-mode
//      auto-repair comments live).
//
// Auto-integration of new sources
// -------------------------------
// New scraper onboarding is one step: drop pulpo/scrapers/<slug>.py.
// The package autodiscovers the new module, the nightly crawls it on
// next run, and this widget displays it after its first row lands in
// source_health_history.jsonl. The /admin/sources widget needs zero
// changes for a new source — same fetch + group-by-source code path.
//
// tests/test_source_integration.py guards the chain — fails CI if any
// scraper module errors on import, fails to register, or lacks a test
// file.

import React, { useCallback, useEffect, useMemo, useState } from "react";

// ── data sources ──────────────────────────────────────────────────────
const HEALTH_HISTORY_PATH = "/data/source_health_history.jsonl";
const LAST_UPDATED_PATH   = "/data/last_updated.json";
const RANKED_LIST_PATH    = "/data/ranked.list.json";

// Ocean-coast slugs from automation/property_types.py VACATION_ZONES.
// Duplicated here on purpose — the JS side has no other reason to know
// the Python list, and keeping the classifier self-contained avoids a
// per-page Python eval. Update when adding a new vacation slug; the
// supply-mix card degrades gracefully (unknown slugs → "inland") so a
// stale list mis-classifies a few listings without breaking the widget.
const BEACH_ZONES = new Set([
  "el-tunco", "el-sunzal", "el-zonte", "san-diego", "mizata",
  "el-cuco", "las-flores", "punta-mango", "el-espino", "conchagua",
  "jiquilisco", "tamanique", "costa-del-sol", "atami",
  "los-cobanos", "palmarcito", "k59", "k61",
  "puerto-de-la-libertad", "surf-city", "el-icacal",
  "las-tunas", "esteron",
]);

// Lake zones are detected by slug prefix "lago-" rather than a static
// set so future additions (Suchitlán, etc.) light up automatically.
function classifyGeo(listing) {
  const z = (listing && listing.zone) || "";
  if (z.startsWith("lago-")) return "lake";
  if (BEACH_ZONES.has(z)) return "beach";
  return "inland";
}

// ── styling ──────────────────────────────────────────────────────────
const STYLES = `
.sw-host { color: var(--ink); font-family: var(--font-sans); }

.sw-card {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--paper);
  margin: 0 0 16px;
}

/* ── Section 1: nightly status strip ──────────────────────────── */
.sw-nightly {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.sw-nightly .left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.sw-nightly .dot {
  width: 10px; height: 10px; border-radius: 50%;
  display: inline-block;
}
.sw-nightly[data-status="green"] .dot { background: var(--badge-new); }
.sw-nightly[data-status="red"]   .dot { background: var(--badge-drop); }
.sw-nightly .big {
  font-weight: 600;
  font-size: 16px;
  color: var(--ink);
}
.sw-nightly .meta { color: var(--ink-3); font-size: 13px; }
.sw-nightly .meta strong { color: var(--ink-2); font-weight: 500; }

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

/* ── Section 2: supply mix card ──────────────────────────────── */
.sw-mix-title {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin: 0 0 12px;
}
.sw-mix {
  display: grid;
  grid-template-columns: 1fr;
  gap: 18px;
}
@media (min-width: 560px) {
  .sw-mix { grid-template-columns: 1fr 1fr; }
}
.sw-mix-block {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.sw-mix-block .lbl {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-3);
}
.sw-legend {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--ink-2);
  min-width: 0;
}
.sw-legend .row {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
.sw-legend .sw { width: 9px; height: 9px; border-radius: 2px; }
.sw-legend .key { color: var(--ink); font-weight: 500; min-width: 56px; }
.sw-legend .pct { color: var(--ink-3); font-family: var(--font-mono); font-size: 11px; }

/* ── Section 3: per-source rows ──────────────────────────────── */
.sw-list { display: grid; gap: 10px; }
.sw-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--paper);
}
@media (min-width: 640px) {
  .sw-row {
    grid-template-columns: 1.4fr 0.9fr 1.3fr 0.9fr;
    align-items: center;
    gap: 14px;
  }
}

.sw-source-line {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 15px;
  min-width: 0;
}
.sw-source-line code {
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
}
.sw-pill[data-status="green"]   { background: color-mix(in oklch, var(--badge-new) 18%, transparent); color: var(--badge-new); }
.sw-pill[data-status="red"]     { background: color-mix(in oklch, var(--badge-drop) 18%, transparent); color: var(--badge-drop); }
.sw-pill[data-status="unknown"] { background: var(--paper-2); color: var(--ink-3); }
.sw-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

.sw-count {
  font-size: 13px;
  color: var(--ink-3);
}
.sw-count .big { font-size: 18px; line-height: 22px; color: var(--ink); font-weight: 600; }
.sw-count .sub { font-family: var(--font-mono); font-size: 11px; color: var(--ink-3); }

.sw-mini { display: flex; gap: 10px; align-items: center; }
.sw-mini .pielbl {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-3);
}

.sw-tail { font-size: 12px; color: var(--ink-3); line-height: 16px; min-width: 0; }
.sw-tail a {
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 12px;
  text-decoration: none;
}
.sw-tail a:hover { text-decoration: underline; }
.sw-tail .err {
  display: block;
  margin-top: 2px;
  color: var(--badge-drop);
  word-break: break-word;
  font-size: 11px;
}

.sw-empty, .sw-error {
  border: 1px dashed var(--line-2);
  border-radius: 10px;
  padding: 18px;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}
.sw-error { color: var(--badge-drop); border-color: var(--badge-drop); }
.sw-loading { font-size: 13px; color: var(--ink-3); padding: 8px 0; }

/* Mobile inline labels — visible only in the stacked layout. */
.sw-row .col-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin-right: 8px;
}
@media (min-width: 640px) { .sw-row .col-label { display: none; } }
`;

// ── palette ──────────────────────────────────────────────────────────
//
// Three tokens used twice each so the geography and type pies share a
// visual language: position-1 = primary (most common), position-2 =
// secondary, position-3 = niche.
const COLORS = {
  beach:  "var(--badge-new)",       // moss
  inland: "var(--accent)",          // brand accent
  lake:   "var(--badge-motivated)", // gold
  land:   "var(--badge-new)",
  house:  "var(--accent)",
  condo:  "var(--badge-motivated)",
};
const GEO_ORDER  = ["beach",  "inland", "lake"];
const TYPE_ORDER = ["land",   "house",  "condo"];
const GEO_LABEL  = { beach: "Beach", inland: "Inland", lake: "Lake" };
const TYPE_LABEL = { land: "Land",  house: "House",  condo: "Condo" };

// ── small SVG donut/pie ──────────────────────────────────────────────
//
// One circle per segment, drawn with stroke-dasharray to give a donut
// look. Cheap to render (no JSX gymnastics, no chart lib) and degrades
// to a single solid colour when one segment is 100%.
function Pie({ segments, size = 56 }) {
  const total = segments.reduce((sum, s) => sum + (s.count || 0), 0);
  if (total === 0) {
    return (
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="14" fill="none" stroke="var(--line-2)" strokeWidth="4" />
      </svg>
    );
  }
  const circumference = 2 * Math.PI * 14;
  let offset = 0;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      {segments.map((seg, i) => {
        const frac = (seg.count || 0) / total;
        const dash = frac * circumference;
        const node = (
          <circle
            key={i}
            cx="16" cy="16" r="14"
            fill="none"
            stroke={seg.color}
            strokeWidth="4"
            strokeDasharray={`${dash} ${circumference - dash}`}
            strokeDashoffset={-offset}
            transform="rotate(-90 16 16)"
          />
        );
        offset += dash;
        return node;
      })}
    </svg>
  );
}

// ── data helpers ─────────────────────────────────────────────────────
function parseJsonl(text) {
  const out = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    try { out.push(JSON.parse(line)); } catch (_) {}
  }
  return out;
}

function groupHealthBySource(rows) {
  const by = new Map();
  for (const r of rows) {
    if (!r || !r.source) continue;
    let arr = by.get(r.source);
    if (!arr) { arr = []; by.set(r.source, arr); }
    arr.push(r);
  }
  for (const arr of by.values()) {
    arr.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));
  }
  return by;
}

function lastGreenTs(rows) {
  for (const r of rows) if (r.status === "green") return r.ts;
  return null;
}

function aggregate(listings) {
  const geo  = { beach: 0, inland: 0, lake: 0 };
  const type = { land: 0, house: 0, condo: 0 };
  for (const r of listings) {
    geo[classifyGeo(r)] = (geo[classifyGeo(r)] || 0) + 1;
    const t = r.property_type;
    if (t && type[t] != null) type[t] += 1;
  }
  return { geo, type, total: listings.length };
}

function formatRelative(iso) {
  if (!iso) return "—";
  const ms = Date.now() - Date.parse(iso);
  if (!Number.isFinite(ms)) return iso;
  const hours = ms / 3_600_000;
  if (hours < 1) return `${Math.max(1, Math.round(ms / 60_000))}m ago`;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function formatDuration(s) {
  if (s == null || !Number.isFinite(s)) return "—";
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return `${m}m${r.toString().padStart(2, "0")}s`;
}

function issueSearchUrl(source) {
  // Land in the GitHub issues list filtered to open issues mentioning
  // the source — the watchdog issue is always the top result, and
  // the Phase-4 shadow-mode comments live there.
  const q = encodeURIComponent(`is:issue is:open ${source}`);
  return `https://github.com/javiersuarezOG/pulpo.club/issues?q=${q}`;
}

// ── component ────────────────────────────────────────────────────────

export function SourcesHealthWidget() {
  const [state, setState] = useState({
    status: "loading",
    healthRows: [],
    lastUpdated: null,
    listings: [],
    fetchedAt: null,
    error: null,
  });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, status: "loading", error: null }));
    try {
      const cb = `?t=${Date.now()}`;
      const [healthText, lastUpdatedRes, listingsRes] = await Promise.all([
        fetch(HEALTH_HISTORY_PATH + cb).then((r) => r.ok ? r.text() : ""),
        fetch(LAST_UPDATED_PATH + cb).then((r) => r.ok ? r.json() : null).catch(() => null),
        fetch(RANKED_LIST_PATH + cb).then((r) => r.ok ? r.json() : []).catch(() => []),
      ]);
      setState({
        status: "ready",
        healthRows: parseJsonl(healthText),
        lastUpdated: lastUpdatedRes,
        listings: Array.isArray(listingsRes) ? listingsRes : [],
        fetchedAt: new Date().toISOString(),
        error: null,
      });
    } catch (e) {
      setState((s) => ({
        ...s,
        status: "error",
        error: e && e.message ? e.message : "fetch failed",
      }));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Pre-compute everything derivable from the fetched data.
  const grouped = useMemo(() => groupHealthBySource(state.healthRows), [state.healthRows]);
  const totals  = useMemo(() => aggregate(state.listings), [state.listings]);
  const perSourceMix = useMemo(() => {
    const out = new Map();
    const bySrc = new Map();
    for (const r of state.listings) {
      if (!r || !r.source) continue;
      let arr = bySrc.get(r.source);
      if (!arr) { arr = []; bySrc.set(r.source, arr); }
      arr.push(r);
    }
    for (const [src, rows] of bySrc) out.set(src, aggregate(rows));
    return out;
  }, [state.listings]);

  // Source ordering — reds first (oldest red on top), then healthy
  // sources by descending count.
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
        const aT = a.lastGreen ? Date.parse(a.lastGreen) : 0;
        const bT = b.lastGreen ? Date.parse(b.lastGreen) : 0;
        return aT - bT;
      }
      return b.latestCount - a.latestCount;
    });
    return entries;
  }, [grouped]);

  const nightlyStatus =
    state.lastUpdated && state.lastUpdated.source_status
      ? Object.values(state.lastUpdated.source_status).every((s) => s === "green") ? "green" : "red"
      : "unknown";

  return (
    <div className="sw-host">
      <style>{STYLES}</style>

      {/* Section 1 — nightly status strip */}
      <div className="sw-card sw-nightly" data-status={nightlyStatus}>
        <div className="left">
          <span className="dot" />
          <span className="big">
            {state.lastUpdated && state.lastUpdated.total_listings != null
              ? `${state.lastUpdated.total_listings} listings`
              : "no data yet"}
          </span>
          <span className="meta">
            {state.lastUpdated && state.lastUpdated.started_at && (
              <>last nightly <strong>{formatRelative(state.lastUpdated.started_at)}</strong></>
            )}
            {state.lastUpdated && state.lastUpdated.duration_seconds && (
              <> · <strong>{formatDuration(state.lastUpdated.duration_seconds)}</strong></>
            )}
          </span>
        </div>
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
        <div className="sw-error">Couldn’t load: {state.error}</div>
      )}

      {/* Section 2 — supply mix */}
      {totals.total > 0 && (
        <div className="sw-card">
          <p className="sw-mix-title">Supply mix · {totals.total} listings</p>
          <div className="sw-mix">
            <SupplyBlock label="Geography" order={GEO_ORDER}  counts={totals.geo}  labels={GEO_LABEL}  total={totals.total} size={64} />
            <SupplyBlock label="Type"      order={TYPE_ORDER} counts={totals.type} labels={TYPE_LABEL} total={totals.total} size={64} />
          </div>
        </div>
      )}

      {/* Section 3 — per-source rows */}
      {state.status === "loading" && sources.length === 0 && (
        <div className="sw-loading">Loading…</div>
      )}

      {state.status === "ready" && sources.length === 0 && (
        <div className="sw-empty">No source health rows yet.</div>
      )}

      {sources.length > 0 && (
        <div className="sw-list" role="list">
          {sources.map((entry) => (
            <SourceRow
              key={entry.source}
              entry={entry}
              mix={perSourceMix.get(entry.source)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SupplyBlock({ label, order, counts, labels, total, size }) {
  const segments = order.map((key) => ({
    key,
    color: COLORS[key],
    count: counts[key] || 0,
  }));
  return (
    <div className="sw-mix-block">
      <Pie segments={segments} size={size} />
      <div className="sw-legend">
        <div className="lbl">{label}</div>
        {order.map((key) => {
          const c = counts[key] || 0;
          const pct = total > 0 ? Math.round((c / total) * 100) : 0;
          return (
            <div className="row" key={key}>
              <span className="sw" style={{ background: COLORS[key] }} />
              <span className="key">{labels[key]}</span>
              <span>{c}</span>
              <span className="pct">({pct}%)</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SourceRow({ entry, mix }) {
  const { source, latest, isRed, lastGreen } = entry;
  const status = latest.status || "unknown";
  const count = latest.count ?? 0;

  const geoSegments = GEO_ORDER.map((key) => ({
    key, color: COLORS[key], count: (mix && mix.geo[key]) || 0,
  }));
  const typeSegments = TYPE_ORDER.map((key) => ({
    key, color: COLORS[key], count: (mix && mix.type[key]) || 0,
  }));
  const hasMix = mix && mix.total > 0;

  return (
    <div className="sw-row" role="listitem" aria-label={`${source} ${status}`}>
      {/* col 1 — name + status */}
      <div className="sw-source-line">
        <code>{source}</code>
        <span className="sw-pill" data-status={status}>
          <span className="dot" /> {status}
        </span>
      </div>

      {/* col 2 — count + last update */}
      <div className="sw-count">
        <span className="col-label">Last run</span>
        <div className="big">{count}</div>
        <div className="sub">{formatRelative(latest.ts)}</div>
      </div>

      {/* col 3 — tiny pies (or "no data" placeholder for red sources) */}
      <div className="sw-mini">
        {hasMix ? (
          <>
            <span className="pielbl">geo</span>
            <Pie segments={geoSegments} size={28} />
            <span className="pielbl">type</span>
            <Pie segments={typeSegments} size={28} />
          </>
        ) : (
          <span className="sub" style={{ color: "var(--ink-3)", fontSize: 12 }}>
            no listings in dataset
          </span>
        )}
      </div>

      {/* col 4 — tail (last good + issue link for reds, healthy status otherwise) */}
      <div className="sw-tail">
        {isRed ? (
          <>
            <span className="col-label">Last good</span>
            <span>{lastGreen ? formatRelative(lastGreen) : "—"}</span>
            <br />
            <a href={issueSearchUrl(source)} target="_blank" rel="noreferrer">
              fix → see issue ↗
            </a>
            {(latest.error_class || latest.error_msg) && (
              <span className="err">
                {latest.error_class && <strong>{latest.error_class}</strong>}
                {latest.error_class && latest.error_msg ? " — " : ""}
                {latest.error_msg && (latest.error_msg.length > 80
                  ? latest.error_msg.slice(0, 80) + "…"
                  : latest.error_msg)}
              </span>
            )}
          </>
        ) : (
          <span style={{ color: "var(--ink-3)" }}>healthy</span>
        )}
      </div>
    </div>
  );
}
