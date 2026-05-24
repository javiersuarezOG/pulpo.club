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

/* ── Section 3: per-source rows ────────────────────────────────
   Single line per source on desktop. Columns:
     [status dot] [name] [count or PR-status] [pies] [last update]
   On mobile they wrap, but the same single-line semantics hold —
   each row remains one logical unit, not a card with internal
   structure. */
.sw-list { display: grid; gap: 6px; }
.sw-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 14px;
  border-bottom: 1px solid var(--line);
  padding: 10px 4px;
  font-size: 14px;
  color: var(--ink-2);
}
.sw-row:last-child { border-bottom: none; }

.sw-row .dot {
  width: 9px; height: 9px; border-radius: 50%;
  flex-shrink: 0;
}
.sw-row[data-status="green"] .dot { background: var(--badge-new); }
.sw-row[data-status="red"]   .dot { background: var(--badge-drop); }
.sw-row[data-status="unknown"] .dot { background: var(--ink-3); }

.sw-row .name {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--ink);
  font-weight: 500;
  min-width: 140px;
}

.sw-row .signal {
  font-size: 14px;
  color: var(--ink);
  font-weight: 500;
  min-width: 130px;
}
.sw-row .signal .sub {
  color: var(--ink-3);
  font-weight: 400;
  font-size: 13px;
}
.sw-row .signal a {
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 13px;
  text-decoration: none;
  font-weight: 500;
}
.sw-row .signal a:hover { text-decoration: underline; }
.sw-row .signal .needs {
  color: var(--badge-drop);
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.04em;
}

.sw-row .pies {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1 1 auto;
  min-width: 80px;
}
.sw-row .pies .gap { width: 6px; }

.sw-row .when {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink-3);
  margin-left: auto;
  white-space: nowrap;
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

// GitHub identity — derived once at module load so the row component
// doesn't recompute it. Hardcoded to the public Pulpo repo since the
// admin tool is internal and not deployed anywhere else.
const GH_OWNER = "javiersuarezOG";
const GH_REPO  = "pulpo.club";

function issueSearchUrl(source) {
  const q = encodeURIComponent(`is:issue is:open ${source}`);
  return `https://github.com/${GH_OWNER}/${GH_REPO}/issues?q=${q}`;
}

// Find open PRs that mention the source slug in title or body. Uses
// GitHub's public Search API — unauthenticated CORS works, rate limit
// 60/hr per IP (plenty for an admin tool refreshed by 1-2 humans).
// Returns the first matching PR or null. On rate-limit / network
// failure, returns null and the row falls back to "needs human".
async function fetchOpenPrForSource(source) {
  const q = encodeURIComponent(
    `is:pr is:open repo:${GH_OWNER}/${GH_REPO} ${source} in:title,body`
  );
  const url = `https://api.github.com/search/issues?q=${q}&per_page=1`;
  try {
    const r = await fetch(url, { headers: { Accept: "application/vnd.github+json" } });
    if (!r.ok) return null;
    const body = await r.json();
    const item = (body && body.items && body.items[0]) || null;
    if (!item) return null;
    return {
      number: item.number,
      title:  item.title,
      url:    item.html_url,
      draft:  Boolean(item.draft),
    };
  } catch (_) {
    return null;
  }
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

  // PR lookup per source slug. Populated lazily when a source goes red
  // — green sources never need this. Keyed by source slug; value is the
  // PR object (number/title/url) or `null` (no PR found / rate-limited).
  // ``undefined`` means "not fetched yet" so the UI can render a
  // "checking…" placeholder.
  const [prs, setPrs] = useState({});

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

  // After health data lands, fan out one PR-search per red source.
  // Effects can't be async directly — kick off the fetches and write
  // results back into `prs` state. The empty-deps + manual guard keeps
  // this from re-firing on every render.
  useEffect(() => {
    if (state.status !== "ready") return;
    const reds = state.healthRows.reduce((acc, r) => {
      // Latest row per source — newest ts wins.
      if (!r || !r.source) return acc;
      const prev = acc[r.source];
      if (!prev || prev.ts < r.ts) acc[r.source] = r;
      return acc;
    }, {});
    const redSlugs = Object.values(reds)
      .filter((row) => row.status === "red")
      .map((row) => row.source);
    for (const slug of redSlugs) {
      if (prs[slug] !== undefined) continue; // already fetched / in-flight
      // Mark in-flight so a re-render doesn't refire the request.
      setPrs((p) => ({ ...p, [slug]: null }));
      void fetchOpenPrForSource(slug).then((result) => {
        setPrs((p) => ({ ...p, [slug]: result }));
      });
    }
  }, [state.status, state.healthRows]); // eslint-disable-line react-hooks/exhaustive-deps

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
              pr={prs[entry.source]}
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

function SourceRow({ entry, mix, pr }) {
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

  // Tail timestamp — for green sources it's the latest run; for red
  // sources it's the last successful run (often more interesting than
  // the latest failure timestamp because it tells you how stale the
  // ingestion is).
  const whenIso = isRed ? lastGreen : latest.ts;
  const whenLabel = isRed
    ? (lastGreen ? `last good ${formatRelative(lastGreen)}` : "never green")
    : formatRelative(latest.ts);

  return (
    <div className="sw-row" data-status={status} role="listitem" aria-label={`${source} ${status}`}>
      <span className="dot" />
      <span className="name">{source}</span>

      {/* Signal column: number of listings (green) OR PR status (red) */}
      <span className="signal">
        {isRed ? (
          // pr === undefined: still fetching the lookup
          // pr === null:      lookup done, no open PR found
          // pr === object:    open PR exists, show its number
          pr === undefined ? (
            <span className="sub">checking for fix…</span>
          ) : pr ? (
            <a href={pr.url} target="_blank" rel="noreferrer" title={pr.title}>
              fix in progress · PR #{pr.number} ↗
            </a>
          ) : (
            <>
              <span className="needs">needs human</span>{" "}
              <a href={issueSearchUrl(source)} target="_blank" rel="noreferrer">
                issue ↗
              </a>
            </>
          )
        ) : (
          <>
            <strong>{count.toLocaleString()}</strong>{" "}
            <span className="sub">listing{count === 1 ? "" : "s"}</span>
          </>
        )}
      </span>

      {/* Per-source supply-mix pies — present even when red (shows the
          historical mix this source contributed; signals what we LOSE
          when it goes red). When the source has no data in ranked.json,
          render empty-state placeholders that align with the column. */}
      <span className="pies" title={hasMix ? "geography · type" : "no listings in dataset"}>
        {hasMix ? (
          <>
            <Pie segments={geoSegments} size={22} />
            <span className="gap" />
            <Pie segments={typeSegments} size={22} />
          </>
        ) : (
          <>
            <Pie segments={[{ count: 0, color: "var(--line-2)" }]} size={22} />
            <span className="gap" />
            <Pie segments={[{ count: 0, color: "var(--line-2)" }]} size={22} />
          </>
        )}
      </span>

      <span className="when" title={whenIso || ""}>{whenLabel}</span>
    </div>
  );
}
