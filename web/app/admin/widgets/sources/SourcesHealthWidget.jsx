// SourcesHealthWidget — at-a-glance per-scraper health for the /admin hub.
//
// Three sections, single page, all from data the nightly already commits:
//
//   1. Nightly status strip — last-run timestamp, duration, total
//      listings, overall green/red. Reads /data/last_updated.json.
//
//   2. Supply mix card — two side-by-side pies (geography + type)
//      computed across every listing in /data/ranked.list.json. This
//      is the "where are the gaps?" view: a tiny condo slice means
//      thin condo inventory, a tiny lake slice means lake supply
//      under-served, and so on.
//
//   3. Per-source cards — one bordered card per scraper.
//
//      Green sources show: count of listings + per-source supply mix
//      (two pies with a legend so you can read "bienesraices is mostly
//      inland land" without hovering).
//
//      Red sources show: a five-state fix banner pulled live from
//      GitHub, in priority order (best → worst):
//        1. `recently fixed`        — PR mentioning the source was
//                                     merged in the last 7 days; the
//                                     next nightly will verify green.
//        2. `fix open`              — open PR mentions the source
//                                     (auto-repair active mode, or
//                                     hand-written).
//        3. `auto-repair running`   — pulpo-scraper-autorepair
//                                     workflow currently in progress.
//        4. `shadow suggestion`     — Phase-4 shadow comment exists on
//                                     the watchdog issue.
//        5. `needs human`           — nothing in flight.
//
// Auto-integration of new sources
// -------------------------------
// New scraper onboarding is one step: drop pulpo/scrapers/<slug>.py.
// The package autodiscovers the new module, the nightly crawls it on
// next run, and this widget displays its card after its first row
// lands in source_health_history.jsonl. The widget needs zero changes
// for a new source — the card list is generated from whatever rows
// the JSONL carries.
//
// tests/test_source_integration.py guards the chain — fails CI if any
// scraper module errors on import, fails to register, or lacks a test
// file.

import React, { useCallback, useEffect, useMemo, useState } from "react";

// ── data sources ──────────────────────────────────────────────────────
const HEALTH_HISTORY_PATH = "/data/source_health_history.jsonl";
const LAST_UPDATED_PATH   = "/data/last_updated.json";
const RANKED_LIST_PATH    = "/data/ranked.list.json";

// GitHub identity — derived once at module load so the row component
// doesn't recompute it. Hardcoded to the public Pulpo repo since the
// admin tool is internal and not deployed anywhere else.
const GH_OWNER  = "javiersuarezOG";
const GH_REPO   = "pulpo.club";
const GH_API    = "https://api.github.com";
const AUTOREPAIR_WORKFLOW_FILE = "pulpo-scraper-autorepair.yml";

// "Recently fixed" window — a PR merged in the last N days counts as
// "fixed, awaiting next nightly verification." After the window
// expires we fall back to "needs human" because the source is still
// red despite a supposed fix.
const RECENTLY_FIXED_WINDOW_DAYS = 7;

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

/* ── Section 3: per-source cards ──────────────────────────────── */
.sw-srclist {
  display: grid;
  grid-template-columns: 1fr;
  gap: 14px;
}
@media (min-width: 800px) {
  .sw-srclist { grid-template-columns: 1fr 1fr; }
}

.sw-srccard {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--paper);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sw-srccard[data-status="red"] {
  border-color: color-mix(in oklch, var(--badge-drop) 40%, var(--line) 60%);
}

.sw-srccard .head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.sw-srccard .name {
  font-family: var(--font-mono);
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  word-break: break-word;
}
.sw-srccard .pill {
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
.sw-srccard .pill[data-status="green"] { background: color-mix(in oklch, var(--badge-new) 18%, transparent); color: var(--badge-new); }
.sw-srccard .pill[data-status="red"]   { background: color-mix(in oklch, var(--badge-drop) 18%, transparent); color: var(--badge-drop); }
.sw-srccard .pill .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

.sw-srccard .signalrow {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.sw-srccard .signal {
  font-size: 16px;
  color: var(--ink);
  font-weight: 600;
}
.sw-srccard .signal .sub {
  color: var(--ink-3);
  font-weight: 400;
  font-size: 13px;
  margin-left: 6px;
}
.sw-srccard .when {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-3);
  white-space: nowrap;
}

.sw-srccard .fixbanner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 18px;
  background: var(--paper-2);
}
.sw-srccard .fixbanner .icon {
  font-family: var(--font-mono);
  font-size: 14px;
  flex-shrink: 0;
}
.sw-srccard .fixbanner.fixed   { background: color-mix(in oklch, var(--badge-new) 14%, transparent); }
.sw-srccard .fixbanner.open    { background: color-mix(in oklch, var(--accent) 14%, transparent); }
.sw-srccard .fixbanner.running { background: color-mix(in oklch, var(--badge-motivated) 18%, transparent); }
.sw-srccard .fixbanner.shadow  { background: color-mix(in oklch, var(--ink-3) 12%, transparent); }
.sw-srccard .fixbanner.human   { background: color-mix(in oklch, var(--badge-drop) 12%, transparent); }
.sw-srccard .fixbanner .label { font-weight: 600; color: var(--ink); }
.sw-srccard .fixbanner .meta {
  color: var(--ink-2);
  flex: 1 1 auto;
  word-break: break-word;
}
.sw-srccard .fixbanner a {
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
}
.sw-srccard .fixbanner a:hover { text-decoration: underline; }

.sw-srccard .mixwrap {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  padding-top: 4px;
}
@media (min-width: 480px) {
  .sw-srccard .mixwrap { grid-template-columns: 1fr 1fr; }
}
.sw-srccard .mixwrap .block {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.sw-srccard .mixwrap .lbl {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-3);
}
.sw-srccard .mixwrap .leg {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--ink-2);
  min-width: 0;
}
.sw-srccard .mixwrap .leg .row {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.sw-srccard .mixwrap .leg .sw {
  width: 8px; height: 8px; border-radius: 2px;
}
.sw-srccard .mixwrap .leg .key { color: var(--ink); font-weight: 500; min-width: 42px; }
.sw-srccard .mixwrap .leg .pct { color: var(--ink-3); font-family: var(--font-mono); font-size: 11px; }

.sw-srccard .nomix {
  font-size: 12px;
  color: var(--ink-3);
  font-style: italic;
}

.sw-srccard .error {
  font-size: 12px;
  color: var(--badge-drop);
  line-height: 16px;
  word-break: break-word;
  margin-top: -4px;
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
const COLORS = {
  beach:  "var(--badge-new)",
  inland: "var(--accent)",
  lake:   "var(--badge-motivated)",
  land:   "var(--badge-new)",
  house:  "var(--accent)",
  condo:  "var(--badge-motivated)",
};
const GEO_ORDER  = ["beach",  "inland", "lake"];
const TYPE_ORDER = ["land",   "house",  "condo"];
const GEO_LABEL  = { beach: "Beach", inland: "Inland", lake: "Lake" };
const TYPE_LABEL = { land: "Land",  house: "House",  condo: "Condo" };

// ── small SVG donut/pie ──────────────────────────────────────────────
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
  const q = encodeURIComponent(`is:issue is:open ${source}`);
  return `https://github.com/${GH_OWNER}/${GH_REPO}/issues?q=${q}`;
}

// ── GitHub API helpers ───────────────────────────────────────────────
//
// GitHub's unauthenticated REST API is rate-limited to 60 req/hr per
// IP for the core API and 10 req/min for the Search API. We hit four
// endpoints per red source on every load(); typical red-source count
// is 0-2 so the budget is comfortable. Failures (network, rate-limit)
// return null, and the fix-state detector falls back gracefully.

async function ghJson(path) {
  try {
    const r = await fetch(`${GH_API}${path}`, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!r.ok) return null;
    return await r.json();
  } catch (_) {
    return null;
  }
}

async function findOpenPrForSource(source) {
  const q = encodeURIComponent(
    `is:pr is:open repo:${GH_OWNER}/${GH_REPO} ${source} in:title,body`
  );
  const body = await ghJson(`/search/issues?q=${q}&per_page=1`);
  const it = body && body.items && body.items[0];
  if (!it) return null;
  return {
    number: it.number,
    title:  it.title,
    url:    it.html_url,
    draft:  Boolean(it.draft),
  };
}

async function findRecentlyMergedPrForSource(source) {
  const since = new Date(Date.now() - RECENTLY_FIXED_WINDOW_DAYS * 86400_000)
    .toISOString().slice(0, 10);
  const q = encodeURIComponent(
    `is:pr is:merged repo:${GH_OWNER}/${GH_REPO} ${source} in:title,body merged:>=${since}`
  );
  const body = await ghJson(`/search/issues?q=${q}&per_page=1&sort=updated&order=desc`);
  const it = body && body.items && body.items[0];
  if (!it) return null;
  return {
    number:    it.number,
    title:     it.title,
    url:       it.html_url,
    mergedAt:  it.closed_at || it.updated_at,
  };
}

async function findRunningAutoRepairForSource(source) {
  const body = await ghJson(
    `/repos/${GH_OWNER}/${GH_REPO}/actions/workflows/${AUTOREPAIR_WORKFLOW_FILE}/runs?status=in_progress&per_page=10`
  );
  if (!body || !Array.isArray(body.workflow_runs)) return null;
  // The workflow_dispatch payload doesn't expose `inputs` on the run
  // listing; match by display title (`autorepair · <source>`) when it
  // exists, otherwise treat any in-progress run as a possible match
  // and let the user click through to confirm.
  for (const run of body.workflow_runs) {
    const title = (run.display_title || run.name || "").toLowerCase();
    if (title.includes(source.toLowerCase()) || body.workflow_runs.length === 1) {
      return {
        id:    run.id,
        url:   run.html_url,
        title: run.display_title || run.name,
        startedAt: run.run_started_at,
      };
    }
  }
  return null;
}

async function findShadowSuggestionForSource(source) {
  // The orchestrator posts shadow comments on the watchdog issue. Find
  // the watchdog issue first (open issue mentioning source), then
  // search its comments for the marker line emitted by
  // scripts/scraper_autorepair.py.
  const issuesQ = encodeURIComponent(`is:issue is:open repo:${GH_OWNER}/${GH_REPO} ${source}`);
  const issuesBody = await ghJson(`/search/issues?q=${issuesQ}&per_page=3`);
  const issues = (issuesBody && issuesBody.items) || [];
  for (const issue of issues) {
    const commentsBody = await ghJson(
      `/repos/${GH_OWNER}/${GH_REPO}/issues/${issue.number}/comments?per_page=20&sort=created&direction=desc`
    );
    if (!Array.isArray(commentsBody)) continue;
    for (const c of commentsBody) {
      if ((c.body || "").includes(`Auto-repair shadow suggestion — \`${source}\``)) {
        return {
          issueNumber: issue.number,
          commentUrl: c.html_url,
          postedAt:   c.created_at,
        };
      }
    }
  }
  return null;
}

// Run all four detection probes for one source in parallel, then pick
// the highest-priority signal. Returns a fix-state record consumed by
// FixBanner. Priority order matches the user-facing UX: a freshly-
// merged PR ("you're done, just wait for nightly") beats an open PR
// ("close to landing") beats a running auto-repair workflow ("in
// progress") beats a shadow suggestion ("proposal exists") beats
// nothing.
async function detectFixState(source) {
  const [merged, open, running, shadow] = await Promise.all([
    findRecentlyMergedPrForSource(source),
    findOpenPrForSource(source),
    findRunningAutoRepairForSource(source),
    findShadowSuggestionForSource(source),
  ]);
  if (merged)  return { kind: "fixed",   detail: merged  };
  if (open)    return { kind: "open",    detail: open    };
  if (running) return { kind: "running", detail: running };
  if (shadow)  return { kind: "shadow",  detail: shadow  };
  return { kind: "human", detail: null };
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

  // Fix-state lookup per source slug. Populated lazily after the
  // health data lands. Undefined = not started; null = checking;
  // object = result.
  const [fixStates, setFixStates] = useState({});

  const load = useCallback(async () => {
    setState((s) => ({ ...s, status: "loading", error: null }));
    setFixStates({}); // re-detect from scratch on manual refresh
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

  // After health data lands, kick off fix-state detection for every
  // red source in parallel. Results land in `fixStates` as each
  // probe completes.
  useEffect(() => {
    if (state.status !== "ready") return;
    const latestByncSource = new Map();
    for (const r of state.healthRows) {
      if (!r || !r.source) continue;
      const prev = latestByncSource.get(r.source);
      if (!prev || prev.ts < r.ts) latestByncSource.set(r.source, r);
    }
    const reds = Array.from(latestByncSource.values()).filter((r) => r.status === "red");
    for (const r of reds) {
      const slug = r.source;
      if (fixStates[slug] !== undefined) continue;
      setFixStates((s) => ({ ...s, [slug]: null })); // mark "checking"
      void detectFixState(slug).then((result) => {
        setFixStates((s) => ({ ...s, [slug]: result }));
      });
    }
  }, [state.status, state.healthRows]); // eslint-disable-line react-hooks/exhaustive-deps

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

      {/* Section 3 — per-source cards */}
      {state.status === "loading" && sources.length === 0 && (
        <div className="sw-loading">Loading…</div>
      )}

      {state.status === "ready" && sources.length === 0 && (
        <div className="sw-empty">No source health rows yet.</div>
      )}

      {sources.length > 0 && (
        <div className="sw-srclist">
          {sources.map((entry) => (
            <SourceCard
              key={entry.source}
              entry={entry}
              mix={perSourceMix.get(entry.source)}
              fixState={fixStates[entry.source]}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SupplyBlock({ label, order, counts, labels, total, size }) {
  const segments = order.map((key) => ({
    key, color: COLORS[key], count: counts[key] || 0,
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

function FixBanner({ source, fixState }) {
  // Five-state banner — see module docstring for the priority order.
  if (fixState === undefined || fixState === null) {
    return (
      <div className="fixbanner shadow">
        <span className="icon">⟳</span>
        <span className="meta">checking GitHub for fix in progress…</span>
      </div>
    );
  }
  const { kind, detail } = fixState;
  if (kind === "fixed") {
    return (
      <div className="fixbanner fixed">
        <span className="icon">✓</span>
        <span className="meta">
          <span className="label">recently fixed</span> — PR #{detail.number} merged{" "}
          {formatRelative(detail.mergedAt)}. Awaiting next nightly to verify green.
        </span>
        <a href={detail.url} target="_blank" rel="noreferrer">PR #{detail.number} ↗</a>
      </div>
    );
  }
  if (kind === "open") {
    return (
      <div className="fixbanner open">
        <span className="icon">→</span>
        <span className="meta">
          <span className="label">fix open</span> — PR #{detail.number}{" "}
          {detail.draft ? "(draft)" : "(ready for review)"}
        </span>
        <a href={detail.url} target="_blank" rel="noreferrer">PR #{detail.number} ↗</a>
      </div>
    );
  }
  if (kind === "running") {
    return (
      <div className="fixbanner running">
        <span className="icon">⟳</span>
        <span className="meta">
          <span className="label">auto-repair running</span> — started{" "}
          {formatRelative(detail.startedAt)}.
        </span>
        <a href={detail.url} target="_blank" rel="noreferrer">run ↗</a>
      </div>
    );
  }
  if (kind === "shadow") {
    return (
      <div className="fixbanner shadow">
        <span className="icon">💬</span>
        <span className="meta">
          <span className="label">shadow suggestion ready</span> — fix proposal posted{" "}
          {formatRelative(detail.postedAt)} on issue #{detail.issueNumber}. Needs human to apply.
        </span>
        <a href={detail.commentUrl} target="_blank" rel="noreferrer">comment ↗</a>
      </div>
    );
  }
  return (
    <div className="fixbanner human">
      <span className="icon">⚠</span>
      <span className="meta">
        <span className="label">needs human</span> — no fix in flight.
      </span>
      <a href={issueSearchUrl(source)} target="_blank" rel="noreferrer">open issue ↗</a>
    </div>
  );
}

function SourceCard({ entry, mix, fixState }) {
  const { source, latest, isRed, lastGreen } = entry;
  const status = latest.status || "unknown";
  const count = latest.count ?? 0;

  const whenIso = isRed ? lastGreen : latest.ts;
  const whenLabel = isRed
    ? (lastGreen ? `last good ${formatRelative(lastGreen)}` : "never green")
    : `${formatRelative(latest.ts)}`;

  const hasMix = mix && mix.total > 0;
  const geoSegments = GEO_ORDER.map((key) => ({
    key, color: COLORS[key], count: (mix && mix.geo[key]) || 0,
  }));
  const typeSegments = TYPE_ORDER.map((key) => ({
    key, color: COLORS[key], count: (mix && mix.type[key]) || 0,
  }));

  return (
    <div className="sw-srccard" data-status={status} aria-label={`${source} ${status}`}>
      <div className="head">
        <span className="name">{source}</span>
        <span className="pill" data-status={status}>
          <span className="dot" /> {status}
        </span>
      </div>

      <div className="signalrow">
        <div className="signal">
          {isRed
            ? <>{count.toLocaleString()} <span className="sub">listings · scraper red</span></>
            : <>{count.toLocaleString()} <span className="sub">listings</span></>}
        </div>
        <div className="when" title={whenIso || ""}>{whenLabel}</div>
      </div>

      {isRed && <FixBanner source={source} fixState={fixState} />}

      {isRed && (latest.error_class || latest.error_msg) && (
        <div className="error">
          {latest.error_class && <strong>{latest.error_class}</strong>}
          {latest.error_class && latest.error_msg ? " — " : ""}
          {latest.error_msg && (latest.error_msg.length > 200
            ? latest.error_msg.slice(0, 200) + "…"
            : latest.error_msg)}
        </div>
      )}

      {hasMix ? (
        <div className="mixwrap">
          <MiniMix label="Geography" order={GEO_ORDER}  counts={mix.geo}  labels={GEO_LABEL}  total={mix.total} segments={geoSegments} />
          <MiniMix label="Type"      order={TYPE_ORDER} counts={mix.type} labels={TYPE_LABEL} total={mix.total} segments={typeSegments} />
        </div>
      ) : (
        <div className="nomix">no listings in current ranked dataset</div>
      )}
    </div>
  );
}

// ── grid-card preview ────────────────────────────────────────────────
//
// Rendered by AdminShell on the /admin grid card *instead of* the
// static description. Shows the at-a-glance signal: how many sources
// are active vs broken, when the last nightly ran, and the total
// listings produced. Keep the surface narrow — the card is ~280px
// wide.

const PREVIEW_STYLES = `
.sw-prev {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
}
.sw-prev .line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  line-height: 18px;
  color: var(--ink-2);
  flex-wrap: wrap;
}
.sw-prev .chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.05em;
  padding: 2px 7px;
  border-radius: 999px;
  font-weight: 500;
}
.sw-prev .chip[data-tone="green"] { background: color-mix(in oklch, var(--badge-new)  18%, transparent); color: var(--badge-new); }
.sw-prev .chip[data-tone="red"]   { background: color-mix(in oklch, var(--badge-drop) 18%, transparent); color: var(--badge-drop); }
.sw-prev .chip .dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.sw-prev .meta {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink-3);
}
.sw-prev .placeholder {
  font-size: 13px;
  color: var(--ink-3);
}
`;

export function SourcesHealthPreview() {
  // Mini-fetch — only the two files needed for the grid summary.
  // The full widget at /admin/sources fetches ranked.list.json too;
  // we intentionally skip it here to keep the /admin page light.
  const [data, setData] = useState({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cb = `?t=${Date.now()}`;
        const [healthText, lastUpdated] = await Promise.all([
          fetch(HEALTH_HISTORY_PATH + cb).then((r) => r.ok ? r.text() : ""),
          fetch(LAST_UPDATED_PATH + cb).then((r) => r.ok ? r.json() : null).catch(() => null),
        ]);
        if (cancelled) return;
        const rows = parseJsonl(healthText);
        const latestByncSource = new Map();
        for (const r of rows) {
          if (!r || !r.source) continue;
          const prev = latestByncSource.get(r.source);
          if (!prev || prev.ts < r.ts) latestByncSource.set(r.source, r);
        }
        const latest = Array.from(latestByncSource.values());
        const active = latest.filter((r) => r.status === "green").length;
        const broken = latest.filter((r) => r.status === "red").length;
        setData({
          status: "ready",
          active,
          broken,
          total:    lastUpdated && lastUpdated.total_listings != null ? lastUpdated.total_listings : null,
          startedAt: lastUpdated && lastUpdated.started_at ? lastUpdated.started_at : null,
        });
      } catch (_) {
        if (!cancelled) setData({ status: "error" });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <style>{PREVIEW_STYLES}</style>
      <div className="sw-prev">
        {data.status === "loading" && (
          <p className="placeholder">Checking nightly status…</p>
        )}
        {data.status === "error" && (
          <p className="placeholder">Couldn’t reach status data.</p>
        )}
        {data.status === "ready" && (
          <>
            <div className="line">
              <span className="chip" data-tone="green">
                <span className="dot" /> {data.active} active
              </span>
              <span className="chip" data-tone={data.broken > 0 ? "red" : "green"}>
                <span className="dot" /> {data.broken} broken
              </span>
            </div>
            <div className="line meta">
              {data.startedAt ? (
                <>last nightly {formatRelative(data.startedAt)}</>
              ) : "no nightly yet"}
              {data.total != null && <> · {data.total.toLocaleString()} listings</>}
            </div>
          </>
        )}
      </div>
    </>
  );
}

function MiniMix({ label, order, counts, labels, total, segments }) {
  return (
    <div className="block">
      <Pie segments={segments} size={40} />
      <div className="leg">
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
