// NewsletterWidget — the newsletter console.
//
// One screen, one row per template. Everything the operator needs to
// answer "is each email healthy, and can I send one?" is on this page,
// and every value is read live from its source of truth — no hardcoded
// versions, no placeholder dates, no "Issue 01" stubs:
//
//   Config & connections   ← /api/admin/newsletter/config-status (env probe)
//   Template version        ← /api/admin/newsletter/template-version
//                             (regex of automation/.../_common.py)
//   Last sent / 7d health   ← /api/admin/newsletter/health (PostHog HogQL)
//   Live audience count     ← /api/admin/newsletter/audience-count (Resend∩Clerk)
//   Activity log            ← /api/admin/newsletter/recent-triggers (PostHog)
//                             merged with this browser's localStorage log
//
// The Config strip is the headline fix over the old widget: a missing
// secret (empty GITHUB_DISPATCH_TOKEN, dropped Resend key, dry-run left
// on) shows as a red row up front, so "why won't it send" is answered
// before the click, not after a cryptic failure.
//
// Auth: none. The /admin surface is intentionally open (operator
// decision 2026-06-10 — the PULPO_ADMIN_DEBUG_TOKEN gate was removed).
// Plain fetch(); the server endpoints keep their rate limits and the
// audience send keeps its type-to-confirm SEND gate.

import React, { useState, useEffect, useCallback } from "react";

const DEFAULT_LOCALE = "en";
const LOCALE_OPTIONS = [
  { value: "en", label: "EN" },
  { value: "es", label: "ES" },
];
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// ── Template registry ───────────────────────────────────────────────
// One row per email Pulpo sends. `id` is the stable key shared across
// three surfaces and MUST match in all of them:
//   • health family id        (api/admin/newsletter/health.js :: FAMILIES)
//   • trigger allow-list value (api/admin/newsletter/trigger-preview.js)
//   • PostHog event key        (newsletter.<id>_sent / _skipped / _failed)
//
//   id           stable key (see above)
//   tier         "pro" | "free" | "system" — drives the chip + grouping
//   title        row heading
//   templateId   key into the template-version map (null = no own version)
//   route        which trigger endpoint a Test send hits:
//                  "preview"  → async GitHub workflow (weekly digests)
//                  "welcome"  → sync /trigger-welcome-test (Pro welcome/-back)
//                  "free"     → sync /trigger-free-welcome-test (Free welcome/-back)
//                  null       → no Test button (automatic-only / system)
//   audience     true → also offers "Send to everyone" (high-blast).
//                Today only Pro · Weekly routes a real audience send.
//   trigger      human note on how the email fires in production
const TEMPLATES = [
  {
    id: "pro-weekly", tier: "pro", title: "Pro · Weekly",
    templateId: "pulpo-pro-general", route: "preview", audience: true,
    trigger: "Mondays 14:00 UTC · cron",
  },
  {
    id: "free-weekly", tier: "free", title: "Free · Weekly",
    templateId: "pulpo-free-general", route: "preview", audience: false,
    trigger: "Mondays 14:00 UTC · cron",
  },
  {
    id: "pro-welcome", tier: "pro", title: "Pro · Welcome",
    templateId: "pulpo-pro-welcome", route: "welcome", audience: false,
    trigger: "Auto · on first Pro payment",
  },
  {
    id: "pro-welcome-back", tier: "pro", title: "Pro · Welcome-back",
    templateId: "pulpo-pro-welcome-back", route: "welcome", audience: false,
    trigger: "Auto · on resubscribe",
  },
  {
    id: "free-welcome", tier: "free", title: "Free · Welcome",
    templateId: "pulpo-free-welcome", route: "free", audience: false,
    trigger: "Auto · on homepage subscribe",
  },
  {
    id: "free-welcome-back", tier: "free", title: "Free · Welcome-back",
    templateId: "pulpo-free-welcome-back", route: "free", audience: false,
    trigger: "Auto · on free resubscribe",
  },
  {
    id: "activation", tier: "system", title: "Activation (Clerk invite)",
    templateId: null, route: null, audience: false,
    trigger: "Auto · Clerk invitation email",
  },
];

// ── Source-of-truth fetchers ────────────────────────────────────────
// All read endpoints graceful-degrade: they never throw, they return a
// neutral shape + an `unavailable_reason` string so the console renders
// "why this is empty" instead of a blank panel.

async function fetchConfig() {
  if (typeof window === "undefined") return { connections: [], all_ready: false, unavailable_reason: null };
  try {
    const r = await fetch("/api/admin/newsletter/config-status", { headers: { accept: "application/json" } });
    if (!r.ok) return { connections: [], all_ready: false, unavailable_reason: `HTTP ${r.status}` };
    const body = await r.json().catch(() => null);
    return {
      connections: Array.isArray(body?.connections) ? body.connections : [],
      all_ready: !!body?.all_ready,
      unavailable_reason: null,
    };
  } catch (err) {
    return { connections: [], all_ready: false, unavailable_reason: String((err && err.message) || err) };
  }
}

async function fetchHealth() {
  if (typeof window === "undefined") return { families: [], unavailable_reason: null };
  try {
    const r = await fetch("/api/admin/newsletter/health", { headers: { accept: "application/json" } });
    if (!r.ok) return { families: [], unavailable_reason: `HTTP ${r.status}` };
    const body = await r.json().catch(() => null);
    return {
      families: Array.isArray(body?.families) ? body.families : [],
      unavailable_reason: typeof body?.unavailable_reason === "string" ? body.unavailable_reason : null,
    };
  } catch (err) {
    return { families: [], unavailable_reason: String((err && err.message) || err) };
  }
}

async function fetchTemplateVersions() {
  if (typeof window === "undefined") return {};
  try {
    const r = await fetch("/api/admin/newsletter/template-version", { headers: { accept: "application/json" } });
    if (!r.ok) return {};
    const body = await r.json().catch(() => null);
    return body && typeof body === "object" ? body : {};
  } catch {
    return {};
  }
}

async function fetchServerLog() {
  if (typeof window === "undefined") return { events: [], unavailable_reason: null };
  try {
    const r = await fetch("/api/admin/newsletter/recent-triggers", { headers: { accept: "application/json" } });
    if (!r.ok) return { events: [], unavailable_reason: `HTTP ${r.status}` };
    const body = await r.json().catch(() => null);
    return {
      events: Array.isArray(body?.events) ? body.events : [],
      unavailable_reason: typeof body?.unavailable_reason === "string" ? body.unavailable_reason : null,
    };
  } catch (err) {
    return { events: [], unavailable_reason: String((err && err.message) || err) };
  }
}

// ── Recent-sends log (per-browser layer) ────────────────────────────
const LOG_LS_KEY = "pulpo-admin-newsletter-trigger-log";
const LOG_CAP = 20;

// The full-audience blast endpoint is open end-to-end like the rest of
// the /admin surface (operator decision 2026-06-10; the endpoint was the
// last holdout, ungated in Batch B). No token dance — the server-side
// guardrails are the type-to-confirm "SEND" string, a 1/hour rate-limit,
// and the GitHub PAT that never leaves the server.

function readLog() {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(LOG_LS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
function writeLog(entries) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LOG_LS_KEY, JSON.stringify(entries.slice(0, LOG_CAP)));
  } catch {
    /* quota / private-mode — the log is a convenience, not a contract */
  }
}
function appendLogEntry(entry) {
  const next = [entry, ...readLog()];
  writeLog(next);
  return next;
}

// Operator identity for the "By" column — read off the same pulpo-user
// localStorage blob app.jsx writes. Falls back to null (renders "—").
function readOperatorEmail() {
  if (typeof window === "undefined") return null;
  try {
    const u = JSON.parse(window.localStorage.getItem("pulpo-user") || "null");
    return typeof u?.email === "string" ? u.email : null;
  } catch {
    return null;
  }
}

// Merge the canonical PostHog log with this browser's localStorage log.
// PostHog wins on duplicates (canonical once ingested); local stays for
// entries PostHog hasn't seen yet (1-5s ingestion lag). Dedupe by `at`.
function mergeLogs(serverEvents, localEvents) {
  const seen = new Set();
  const out = [];
  for (const e of serverEvents) {
    if (!e || !e.at) continue;
    seen.add(e.at);
    out.push(e);
  }
  for (const e of localEvents) {
    if (!e || !e.at || seen.has(e.at)) continue;
    out.push(e);
  }
  out.sort((a, b) => (b.at || "").localeCompare(a.at || ""));
  return out.slice(0, LOG_CAP);
}

// "just now" / "5 min ago" / "3 h ago" / absolute past ~6h. Shared by the
// log and the per-template "last sent" cell so latency reads at a glance.
function formatWhen(iso, now = new Date()) {
  if (!iso) return "—";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "—";
  const min = Math.round((now.getTime() - t.getTime()) / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 6) return `${hr} h ago`;
  return t.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// Map a health family row to a status dot. red (failures) > amber
// (dry-run-only / skip-only) > green (real sends) > grey (idle).
function healthStatus(row) {
  if (!row) return { kind: "idle", label: "no activity" };
  if (row.failed > 0) return { kind: "fail", label: `${row.failed} failed` };
  if (row.sent > 0 && row.dry_run === true) return { kind: "dry", label: "dry-run only" };
  if (row.sent > 0) return { kind: "ok", label: `${row.sent} sent` };
  if (row.skipped > 0) return { kind: "skip", label: `${row.skipped} skipped` };
  return { kind: "idle", label: "no activity" };
}

const WIDGET_STYLES = `
.nl-console { color: var(--ink); font-family: var(--font-sans); max-width: 920px; }
.nl-console .nl-sec { margin: 0 0 28px; }
.nl-console .nl-sec-title {
  font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--ink-3); margin: 0 0 12px;
  display: flex; align-items: center; gap: 8px;
}
.nl-console .nl-sec-title .nl-count {
  background: var(--paper-2); border: 1px solid var(--line); border-radius: 999px;
  padding: 1px 8px; font-size: 10px; color: var(--ink-2);
}
.nl-console .nl-muted { color: var(--ink-3); font-size: 12px; }
.nl-console code { font-family: var(--font-mono); font-size: 0.9em; }

/* ── Header: test-to field + send-mode pill ── */
.nl-console .nl-head {
  display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end;
  justify-content: space-between; margin: 0 0 24px;
}
.nl-console .nl-testfield { flex: 1; min-width: 240px; }
.nl-console .nl-testfield label {
  display: block; font-size: 12px; color: var(--ink-2); margin: 0 0 5px; font-weight: 600;
}
.nl-console .nl-testfield input {
  width: 100%; border: 1px solid var(--line-2); border-radius: 8px;
  background: var(--paper); color: var(--ink); font: inherit; padding: 9px 11px;
}
.nl-console .nl-testfield input:focus { outline: 2px solid var(--clay, #B8643C); outline-offset: 1px; }
.nl-console .nl-mode-pill {
  display: inline-flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600;
  padding: 7px 12px; border-radius: 999px; white-space: nowrap;
}
.nl-console .nl-mode-pill .nl-dot { width: 8px; height: 8px; border-radius: 50%; }
.nl-console .nl-mode-pill.live { background: #E2F1E7; color: #1F6B43; }
.nl-console .nl-mode-pill.live .nl-dot { background: #2F8F5B; }
.nl-console .nl-mode-pill.dry { background: #F6ECD5; color: #8A6314; }
.nl-console .nl-mode-pill.dry .nl-dot { background: #B9821F; }

/* ── Config & connections ── */
.nl-console .nl-conf { display: grid; grid-template-columns: 1fr; gap: 8px; }
@media (min-width: 600px) { .nl-console .nl-conf { grid-template-columns: 1fr 1fr; } }
.nl-console .nl-conf-row {
  display: flex; align-items: center; gap: 10px; font-size: 13px;
  border: 1px solid var(--line); border-radius: 9px; padding: 9px 12px; background: var(--paper);
}
.nl-console .nl-conf-row .nl-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.nl-console .nl-conf-row .nl-k { font-weight: 600; flex: none; }
.nl-console .nl-conf-row .nl-v { color: var(--ink-2); font-size: 12px; margin-left: auto; text-align: right; }
.nl-console .nl-conf-row.ok { border-color: #CFE7D8; }
.nl-console .nl-conf-row.ok .nl-dot { background: #2F8F5B; }
.nl-console .nl-conf-row.warn { border-color: #ECD9AE; background: #FBF6EA; }
.nl-console .nl-conf-row.warn .nl-dot { background: #B9821F; }
.nl-console .nl-conf-row.warn .nl-v { color: #8A6314; }
.nl-console .nl-conf-row.bad { border-color: #E4B4AE; background: #FBEDEB; }
.nl-console .nl-conf-row.bad .nl-dot { background: #C0392B; }
.nl-console .nl-conf-row.bad .nl-v { color: #A23227; font-weight: 600; }
.nl-console .nl-conf-blocks { font-size: 11px; color: var(--ink-3); margin: 6px 2px 0; }

/* ── Template rows ── */
.nl-console .nl-tpl {
  border: 1px solid var(--line); border-radius: 12px; background: var(--paper);
  padding: 14px 16px; margin: 0 0 10px;
}
.nl-console .nl-tpl-top {
  display: grid; grid-template-columns: 1fr auto; gap: 8px 14px; align-items: start;
}
.nl-console .nl-tpl-title { font-size: 15px; font-weight: 700; margin: 0; }
.nl-console .nl-chips { display: flex; flex-wrap: wrap; gap: 5px; margin: 6px 0 0; }
.nl-console .nl-chip {
  font-size: 10px; font-weight: 600; letter-spacing: 0.02em; padding: 2px 7px; border-radius: 999px;
}
.nl-console .nl-chip.pro { background: #EFE7FB; color: #6D3FB0; }
.nl-console .nl-chip.free { background: var(--paper-3); color: var(--ink-2); }
.nl-console .nl-chip.system { background: var(--paper-3); color: var(--ink-3); }
.nl-console .nl-chip.ver { background: #F4E2D6; color: #9A4A1E; font-family: var(--font-mono); }
.nl-console .nl-hd {
  display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600;
  padding: 3px 9px; border-radius: 999px; white-space: nowrap; justify-self: end;
}
.nl-console .nl-hd .nl-dot { width: 7px; height: 7px; border-radius: 50%; }
.nl-console .nl-hd.ok { background: #E2F1E7; color: #1F6B43; } .nl-console .nl-hd.ok .nl-dot { background: #2F8F5B; }
.nl-console .nl-hd.dry { background: #F6ECD5; color: #8A6314; } .nl-console .nl-hd.dry .nl-dot { background: #B9821F; }
.nl-console .nl-hd.skip { background: #F6ECD5; color: #8A6314; } .nl-console .nl-hd.skip .nl-dot { background: #B9821F; }
.nl-console .nl-hd.fail { background: #FBEDEB; color: #A23227; } .nl-console .nl-hd.fail .nl-dot { background: #C0392B; }
.nl-console .nl-hd.idle { background: var(--paper-3); color: var(--ink-3); } .nl-console .nl-hd.idle .nl-dot { background: var(--ink-4); }
.nl-console .nl-tpl-meta {
  display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 12px 0 0; font-size: 12px; color: var(--ink-2);
}
.nl-console .nl-tpl-meta b { color: var(--ink); font-weight: 600; }
.nl-console .nl-tpl-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 13px 0 0; }
.nl-console .nl-btn {
  border-radius: 8px; padding: 8px 14px; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
  border: 1px solid var(--line-2); background: var(--paper); color: var(--ink);
}
.nl-console .nl-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.nl-console .nl-btn.test { border-color: var(--clay, #B8643C); color: var(--clay, #B8643C); }
.nl-console .nl-btn.send { border-color: var(--clay, #B8643C); background: var(--clay, #B8643C); color: #fff; }

/* per-row locale toggle */
.nl-console .nl-loc { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; }
.nl-console .nl-loc-label { font-size: 11px; color: var(--ink-3); }
.nl-console .nl-loc-toggle { display: inline-flex; border: 1px solid var(--line-2); border-radius: 7px; overflow: hidden; }
.nl-console .nl-loc-btn {
  border: none; background: var(--paper); color: var(--ink-2); font: inherit; font-size: 11px;
  font-weight: 600; padding: 5px 9px; cursor: pointer;
}
.nl-console .nl-loc-btn[aria-pressed="true"] { background: var(--ink); color: var(--paper); }

/* inline status under a row */
.nl-console .nl-status {
  display: flex; align-items: center; gap: 8px; margin: 11px 0 0; font-size: 13px;
  border-radius: 8px; padding: 9px 11px;
}
.nl-console .nl-status .nl-si { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.nl-console .nl-status.pending { background: var(--paper-2); color: var(--ink-2); }
.nl-console .nl-status.pending .nl-si { background: var(--ink-4); animation: nlpulse 1s ease-in-out infinite; }
.nl-console .nl-status.ok { background: #E2F1E7; color: #1F6B43; } .nl-console .nl-status.ok .nl-si { background: #2F8F5B; }
.nl-console .nl-status.warn { background: #F6ECD5; color: #8A6314; } .nl-console .nl-status.warn .nl-si { background: #B9821F; }
.nl-console .nl-status.err { background: #FBEDEB; color: #A23227; } .nl-console .nl-status.err .nl-si { background: #C0392B; }
.nl-console .nl-status a { color: inherit; text-decoration: underline; }
@keyframes nlpulse { 0%,100% { opacity: 0.35; } 50% { opacity: 1; } }

/* audience-send confirm */
.nl-console .nl-confirm {
  margin: 12px 0 0; border: 1px solid var(--clay, #B8643C); border-radius: 10px;
  background: #FFF8F0; padding: 13px 15px;
}
.nl-console .nl-confirm h4 { margin: 0 0 6px; font-size: 14px; }
.nl-console .nl-confirm p { margin: 0 0 10px; font-size: 13px; color: var(--ink-2); }
.nl-console .nl-confirm .nl-cfields { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.nl-console .nl-confirm input {
  border: 1px solid var(--line-2); border-radius: 7px; background: var(--paper);
  color: var(--ink); font: inherit; padding: 7px 9px;
}
.nl-console .nl-confirm input.issue { width: 90px; }
.nl-console .nl-confirm input.confirm { width: 130px; letter-spacing: 0.1em; }
.nl-console .nl-confirm .nl-cactions { display: flex; gap: 8px; margin: 11px 0 0; }
.nl-console .nl-confirm .nl-btn.cancel { border-color: var(--line-2); color: var(--ink-2); }

/* activity log */
.nl-console .nl-log-head { display: flex; align-items: center; justify-content: space-between; }
.nl-console .nl-log-clear {
  border: 1px solid var(--line-2); background: var(--paper); color: var(--ink-2);
  border-radius: 7px; font: inherit; font-size: 12px; padding: 5px 10px; cursor: pointer;
}
.nl-console .nl-log {
  border: 1px solid var(--line); border-radius: 12px; background: var(--paper); overflow: hidden;
}
.nl-console .nl-log-row {
  display: grid; grid-template-columns: auto 1fr auto; gap: 4px 12px; align-items: center;
  padding: 10px 14px; border-bottom: 1px solid var(--line); font-size: 13px;
}
.nl-console .nl-log-row:last-child { border-bottom: none; }
.nl-console .nl-log-when { color: var(--ink-3); font-size: 12px; white-space: nowrap; }
.nl-console .nl-log-main b { font-weight: 600; }
.nl-console .nl-log-sub { color: var(--ink-3); font-size: 11px; }
.nl-console .nl-res {
  font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
  padding: 2px 8px; border-radius: 999px; white-space: nowrap;
}
.nl-console .nl-res.ok { background: #E2F1E7; color: #1F6B43; }
.nl-console .nl-res.dispatched { background: #E6EEF6; color: #2B5786; }
.nl-console .nl-res.dry_run { background: #F6ECD5; color: #8A6314; }
.nl-console .nl-res.skipped { background: var(--paper-3); color: var(--ink-2); }
.nl-console .nl-res.failed, .nl-console .nl-res.error { background: #FBEDEB; color: #A23227; }
.nl-console .nl-log-empty { padding: 20px; text-align: center; color: var(--ink-3); font-size: 13px; }
`;

// Honest, actionable copy for sync welcome outcomes (admin-only — JSX
// text content, not linted; no t() needed on this internal surface).
const WELCOME_SKIP_TEXT = {
  not_pro: "that email's account isn't Pro — the Pro welcome only renders for a Pro member. Use an existing Pro member's email.",
  clerk_lookup_failed: "no Clerk member for that email — test with an existing Pro member's email (a fresh address can't be used here).",
  ranked_missing: "listings data is unavailable right now — try again shortly.",
  no_picks_available: "no listings were available to include.",
  already_sent: "already sent (idempotency stamp) — re-send forces past it.",
  already_sent_for_subscription: "already sent for this subscription.",
};
const DISPATCH_ERROR_TEXT = {
  rate_limited: "Test-send limit reached (20 per hour) — give it a bit and try again.",
  github_dispatch_not_configured: "Server can't dispatch the run (GITHUB_DISPATCH_TOKEN missing in env).",
  github_dispatch_not_configured_repo: "Server can't dispatch the run (dispatch repo/ref not configured).",
  invalid_newsletter_id: "That newsletter id isn't recognized by the dispatcher.",
  invalid_email: "Enter a valid email address.",
  internal_endpoint_not_configured: "Welcome dispatcher not configured (PULPO_INTERNAL_TOKEN missing in env).",
  method_not_allowed: "Unexpected request — refresh and try again.",
};
const reasonText = (r) => WELCOME_SKIP_TEXT[r] || r || "unknown reason";
const dispatchErrorText = (c) => DISPATCH_ERROR_TEXT[c] || c || "unknown error";

export function NewsletterWidget() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [localeByNl, setLocaleByNl] = useState({});
  const localeFor = (id) => localeByNl[id] || DEFAULT_LOCALE;
  const setLocaleFor = (id, loc) => setLocaleByNl((m) => ({ ...m, [id]: loc }));

  // Per-row status: { [id]: { kind, message?, recipient?, runsUrl? } }
  const [statusById, setStatusById] = useState({});
  const setStatusFor = useCallback((id, next) => setStatusById((p) => ({ ...p, [id]: next })), []);
  const statusFor = (id) => statusById[id] || { kind: null };

  // Source-of-truth state.
  const [config, setConfig] = useState({ connections: [], all_ready: false, unavailable_reason: null, loaded: false });
  const [health, setHealth] = useState({ families: [], unavailable_reason: null });
  // Named `templateVersions` (not `versions`) — the Python guard
  // tests/newsletter/test_templates.py greps the widget for a
  // `templateVersions[...]` read to prove the chrome renders FETCHED
  // versions, never a hardcoded mirror. Keep the name in lock-step.
  const [templateVersions, setTemplateVersions] = useState({});
  const [serverEntries, setServerEntries] = useState([]);
  const [serverUnavailable, setServerUnavailable] = useState(null);
  const [localEntries, setLocalEntries] = useState(() => readLog());

  const refreshServerLog = useCallback(async () => {
    const { events, unavailable_reason } = await fetchServerLog();
    setServerEntries(events);
    setServerUnavailable(unavailable_reason);
  }, []);
  const refreshHealth = useCallback(async () => {
    setHealth(await fetchHealth());
  }, []);
  useEffect(() => {
    fetchConfig().then((c) => setConfig({ ...c, loaded: true }));
    refreshHealth();
    refreshServerLog();
    fetchTemplateVersions().then(setTemplateVersions);
  }, [refreshHealth, refreshServerLog]);

  const log = mergeLogs(serverEntries, localEntries);
  const healthById = {};
  for (const f of health.families) healthById[f.id] = f;
  const sendModeRow = config.connections.find((c) => c.id === "send_mode");
  const dryRun = sendModeRow ? sendModeRow.status === "warn" : null;

  // ── Test-send trigger ──────────────────────────────────────────────
  const trigger = async (tpl) => {
    const value = email.trim().toLowerCase();
    if (!value || !EMAIL_RE.test(value)) {
      setStatusFor(tpl.id, { kind: "err", message: "Enter a valid email address above." });
      return;
    }
    const locale = localeFor(tpl.id);
    const operatorEmail = readOperatorEmail();
    setBusy(true);
    setStatusFor(tpl.id, { kind: "pending", message: "Sending…" });
    const baseEntry = { at: new Date().toISOString(), to: value, locale, by: operatorEmail, newsletter_id: tpl.id };

    const endpoint = tpl.route === "welcome"
      ? "/api/admin/newsletter/trigger-welcome-test"
      : tpl.route === "free"
        ? "/api/admin/newsletter/trigger-free-welcome-test"
        : "/api/admin/newsletter/trigger-preview";

    try {
      const payload = { email: value, by: operatorEmail || undefined, locale };
      if (tpl.route === "welcome") {
        if (tpl.id === "pro-welcome-back") payload.variant = "welcome_back";
      } else if (tpl.route === "free") {
        payload.variant = tpl.id === "free-welcome-back" ? "free_welcome_back" : "free_welcome";
      } else {
        payload.newsletter_id = tpl.id;
      }
      const r = await fetch(endpoint, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json().catch(() => ({}));

      // Synchronous routes (welcome / free) return the REAL outcome.
      if (tpl.route === "welcome" || tpl.route === "free") {
        const st = body.status;
        if (st === "sent") {
          setStatusFor(tpl.id, {
            kind: "ok",
            message: body.dry_run
              ? `Rendered to ${value} · dry-run (no email left the building)`
              : `Sent to ${value} ✓`,
          });
          setLocalEntries(appendLogEntry({ ...baseEntry, result: body.dry_run ? "dry_run" : "ok" }));
        } else if (st === "skipped") {
          setStatusFor(tpl.id, { kind: "warn", message: `Skipped — ${reasonText(body.reason)}` });
          setLocalEntries(appendLogEntry({ ...baseEntry, result: "skipped", detail: body.reason || "" }));
        } else if (st === "failed") {
          setStatusFor(tpl.id, { kind: "err", message: `Failed — ${reasonText(body.reason)}` });
          setLocalEntries(appendLogEntry({ ...baseEntry, result: "failed", detail: body.reason || "" }));
        } else {
          const friendly = body.reason ? reasonText(body.reason)
            : body.error ? dispatchErrorText(body.error) : `HTTP ${r.status}`;
          setStatusFor(tpl.id, { kind: "err", message: friendly });
          setLocalEntries(appendLogEntry({ ...baseEntry, result: "error", detail: body.reason || body.error || `HTTP ${r.status}` }));
        }
        return;
      }

      // Async preview route — we only know it was DISPATCHED.
      if (!r.ok) {
        let friendly = body.error ? dispatchErrorText(body.error) : `HTTP ${r.status}`;
        if (body.error === "rate_limited" && body.retry_after_s) {
          const mins = Math.max(1, Math.ceil(body.retry_after_s / 60));
          friendly = `Test-send limit reached (20 per hour) — try again in ~${mins} min.`;
        }
        setStatusFor(tpl.id, { kind: "err", message: friendly });
        setLocalEntries(appendLogEntry({ ...baseEntry, result: "error", detail: body.error || `HTTP ${r.status}` }));
        return;
      }
      setStatusFor(tpl.id, {
        kind: "ok",
        message: `Dispatched · 1 preview email to ${value} (~30–60s via GitHub Actions)`,
        runsUrl: body.runs_url || null,
      });
      setLocalEntries(appendLogEntry({ ...baseEntry, result: "dispatched" }));
    } catch (err) {
      const msg = String((err && err.message) || err);
      setStatusFor(tpl.id, { kind: "err", message: msg });
      setLocalEntries(appendLogEntry({ ...baseEntry, result: "error", detail: msg }));
    } finally {
      setBusy(false);
      // Promote the just-fired entry from local-only to PostHog-canonical
      // once ingestion lands (~1-5s). Merge dedupes by `at`, no flicker.
      window.setTimeout(() => { refreshServerLog(); refreshHealth(); }, 5000);
    }
  };

  // ── Audience send (Pro · Weekly only, high blast) ──────────────────
  // State: null | { phase, audienceCount, issueInput, typedConfirm, runsUrl, errorMessage }
  const [audienceConfirm, setAudienceConfirm] = useState(null);

  const openAudienceConfirm = useCallback(async () => {
    setAudienceConfirm({ phase: "loading_count", audienceCount: null, issueInput: "", typedConfirm: "", runsUrl: null, errorMessage: null });
    try {
      const r = await fetch("/api/admin/newsletter/audience-count");
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setAudienceConfirm((p) => p ? { ...p, phase: "error", errorMessage: body.error || `Couldn't load audience count (HTTP ${r.status})` } : p);
        return;
      }
      setAudienceConfirm((p) => p ? { ...p, phase: "ready", audienceCount: typeof body.count === "number" ? body.count : 0 } : p);
    } catch (err) {
      setAudienceConfirm((p) => p ? { ...p, phase: "error", errorMessage: String((err && err.message) || err) } : p);
    }
  }, []);

  const submitAudienceConfirm = useCallback(async () => {
    const snap = audienceConfirm;
    if (!snap) return;
    // Open endpoint — the server-side type-to-confirm "SEND" gate + the
    // 1/hour rate-limit are the guardrails; no admin token needed.
    setAudienceConfirm((p) => p ? { ...p, phase: "submitting", errorMessage: null } : p);
    const operatorEmail = readOperatorEmail();
    try {
      const r = await fetch("/api/admin/newsletter/trigger-audience-send", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          confirm: snap.typedConfirm,
          issue_number: Number(snap.issueInput),
          audience_count: snap.audienceCount,
          by: operatorEmail || undefined,
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const hint = body.hint ? ` — ${body.hint}` : "";
        setAudienceConfirm((p) => p ? { ...p, phase: "error", errorMessage: `${body.error || `HTTP ${r.status}`}${hint}` } : p);
        return;
      }
      setAudienceConfirm((p) => p ? { ...p, phase: "dispatched", runsUrl: body.runs_url_hint || null } : p);
      setLocalEntries(appendLogEntry({
        at: new Date().toISOString(), to: `all · ${snap.audienceCount} readers`,
        locale: DEFAULT_LOCALE, by: operatorEmail, newsletter_id: "pro-weekly", result: "dispatched",
      }));
      window.setTimeout(() => { refreshServerLog(); refreshHealth(); }, 5000);
    } catch (err) {
      setAudienceConfirm((p) => p ? { ...p, phase: "error", errorMessage: String((err && err.message) || err) } : p);
    }
  }, [audienceConfirm, refreshServerLog, refreshHealth]);

  const clearLog = () => { writeLog([]); setLocalEntries([]); };

  // issue number must be a positive int ≤ 9999 (server contract).
  const issueValid = (() => {
    if (!audienceConfirm) return false;
    const n = Number(audienceConfirm.issueInput);
    return Number.isInteger(n) && n > 0 && n <= 9999;
  })();
  const confirmReady = issueValid && audienceConfirm?.typedConfirm === "SEND";

  const localeToggle = (tpl) => (
    <span className="nl-loc">
      <span className="nl-loc-label">Lang</span>
      <span className="nl-loc-toggle">
        {LOCALE_OPTIONS.map((opt) => (
          <button
            key={opt.value} type="button" className="nl-loc-btn"
            aria-pressed={localeFor(tpl.id) === opt.value}
            onClick={() => setLocaleFor(tpl.id, opt.value)} disabled={busy}
          >
            {opt.label}
          </button>
        ))}
      </span>
    </span>
  );

  return (
    <>
      <style>{WIDGET_STYLES}</style>
      <div className="nl-console">

        {/* Header — test recipient + send-mode pill */}
        <div className="nl-head">
          <div className="nl-testfield">
            <label htmlFor="nl-test-to">Send test to</label>
            <input
              id="nl-test-to" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@pulpo.club" // i18n-allow: admin-only operator surface, never shown to end users
              autoComplete="off"
            />
          </div>
          {dryRun != null && (
            <span className={`nl-mode-pill ${dryRun ? "dry" : "live"}`}>
              <span className="nl-dot" />
              {dryRun ? "Dry-run — no live mail" : "Live — real mail sends"}
            </span>
          )}
        </div>

        {/* Config & connections */}
        <section className="nl-sec">
          <p className="nl-sec-title">Config &amp; connections <span className="nl-count">live</span></p>
          {config.unavailable_reason ? (
            <p className="nl-muted">Config probe unavailable — {config.unavailable_reason}</p>
          ) : !config.loaded ? (
            <p className="nl-muted">Loading…</p>
          ) : (
            <>
              <div className="nl-conf">
                {config.connections.map((c) => (
                  <div key={c.id} className={`nl-conf-row ${c.status}`} title={c.blocks ? `Blocks: ${c.blocks}` : undefined}>
                    <span className="nl-dot" />
                    <span className="nl-k">{c.label}</span>
                    <span className="nl-v">{c.detail}</span>
                  </div>
                ))}
              </div>
              {config.connections.some((c) => c.status === "bad") && (
                <p className="nl-conf-blocks">
                  A red row above means that dependency's send path is broken until the env var is set. Hover a row for what it blocks.
                </p>
              )}
            </>
          )}
        </section>

        {/* Templates */}
        <section className="nl-sec">
          <p className="nl-sec-title">Templates <span className="nl-count">{TEMPLATES.length}</span></p>
          {TEMPLATES.map((tpl) => {
            const ver = tpl.templateId ? templateVersions[tpl.templateId] : null;
            const hrow = healthById[tpl.id];
            const hs = healthStatus(hrow);
            const st = statusFor(tpl.id);
            const confirmOpen = tpl.audience && !!audienceConfirm;
            return (
              <div key={tpl.id} className="nl-tpl">
                <div className="nl-tpl-top">
                  <div>
                    <p className="nl-tpl-title">{tpl.title}</p>
                    <div className="nl-chips">
                      <span className={`nl-chip ${tpl.tier}`}>{tpl.tier.toUpperCase()}</span>
                      {ver?.version
                        ? <span className="nl-chip ver">{ver.version}</span>
                        : tpl.templateId ? <span className="nl-chip ver">—</span> : null}
                    </div>
                  </div>
                  <span className={`nl-hd ${hs.kind}`}><span className="nl-dot" />{hs.label}</span>
                </div>

                <div className="nl-tpl-meta">
                  <span>Last sent <b>{formatWhen(hrow?.last_sent_at)}</b></span>
                  <span>7d <b>{hrow?.sent ?? 0}</b> sent · <b>{hrow?.skipped ?? 0}</b> skip · <b>{hrow?.failed ?? 0}</b> fail</span>
                  {ver?.lastUpdated && <span>Template <b>{ver.lastUpdated}</b></span>}
                  <span>{tpl.trigger}</span>
                </div>

                {tpl.route && (
                  <div className="nl-tpl-actions">
                    <button type="button" className="nl-btn test" disabled={busy} onClick={() => trigger(tpl)}>
                      Send test →
                    </button>
                    {tpl.audience && (
                      <button type="button" className="nl-btn send" disabled={busy || confirmOpen} onClick={openAudienceConfirm}>
                        Send to everyone
                      </button>
                    )}
                    {(tpl.route === "welcome" || tpl.route === "free") && localeToggle(tpl)}
                  </div>
                )}

                {/* inline status */}
                {st.kind && (
                  <div className={`nl-status ${st.kind}`}>
                    <span className="nl-si" />
                    <span>
                      {st.message}
                      {st.runsUrl && (
                        <> · <a href={st.runsUrl} target="_blank" rel="noreferrer">view run →</a></>
                      )}
                    </span>
                  </div>
                )}

                {/* audience-send confirm (pro-weekly) */}
                {confirmOpen && (
                  <div className="nl-confirm">
                    {audienceConfirm.phase === "loading_count" && <p>Counting live audience (Resend ∩ Clerk Pro)…</p>}
                    {audienceConfirm.phase === "error" && (
                      <>
                        <h4>Couldn't start the send</h4>
                        <p>{audienceConfirm.errorMessage}</p>
                        <div className="nl-cactions">
                          <button type="button" className="nl-btn cancel" onClick={() => setAudienceConfirm(null)}>Close</button>
                        </div>
                      </>
                    )}
                    {audienceConfirm.phase === "dispatched" && (
                      <>
                        <h4>Dispatched ✓</h4>
                        <p>
                          The weekly send is running to {audienceConfirm.audienceCount} readers.
                          {audienceConfirm.runsUrl && <> <a href={audienceConfirm.runsUrl} target="_blank" rel="noreferrer">View run →</a></>}
                        </p>
                        <div className="nl-cactions">
                          <button type="button" className="nl-btn cancel" onClick={() => setAudienceConfirm(null)}>Done</button>
                        </div>
                      </>
                    )}
                    {(audienceConfirm.phase === "ready" || audienceConfirm.phase === "submitting") && (
                      <>
                        <h4>Send the weekly to {audienceConfirm.audienceCount} readers?</h4>
                        <p>This emails every Pro/Agency subscriber. Set the issue number, then type <code>SEND</code> to confirm.</p>
                        <div className="nl-cfields">
                          <input
                            className="issue" type="number" min="1" max="9999"
                            value={audienceConfirm.issueInput}
                            onChange={(e) => setAudienceConfirm((p) => p ? { ...p, issueInput: e.target.value } : p)}
                            placeholder="Issue #" // i18n-allow: admin-only operator surface
                            disabled={audienceConfirm.phase === "submitting"}
                          />
                          <input
                            className="confirm" type="text"
                            value={audienceConfirm.typedConfirm}
                            onChange={(e) => setAudienceConfirm((p) => p ? { ...p, typedConfirm: e.target.value } : p)}
                            placeholder="type SEND" // i18n-allow: admin-only operator surface
                            disabled={audienceConfirm.phase === "submitting"}
                          />
                        </div>
                        <div className="nl-cactions">
                          <button
                            type="button" className="nl-btn send"
                            disabled={!confirmReady || audienceConfirm.phase === "submitting"}
                            onClick={submitAudienceConfirm}
                          >
                            {audienceConfirm.phase === "submitting" ? "Sending…" : `Send Issue ${issueValid ? Number(audienceConfirm.issueInput) : "—"} →`}
                          </button>
                          <button
                            type="button" className="nl-btn cancel"
                            disabled={audienceConfirm.phase === "submitting"}
                            onClick={() => setAudienceConfirm(null)}
                          >
                            Cancel
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {health.unavailable_reason && (
            <p className="nl-conf-blocks">Health unavailable — {health.unavailable_reason}</p>
          )}
        </section>

        {/* Activity log */}
        <section className="nl-sec">
          <div className="nl-log-head">
            <p className="nl-sec-title" style={{ margin: 0 }}>Activity <span className="nl-count">PostHog + this device</span></p>
            {localEntries.length > 0 && (
              <button type="button" className="nl-log-clear" onClick={clearLog}>Clear local</button>
            )}
          </div>
          <div className="nl-log" style={{ marginTop: 12 }}>
            {log.length === 0 ? (
              <div className="nl-log-empty">
                {serverUnavailable
                  ? `No activity yet. Cross-device log unavailable — ${serverUnavailable}`
                  : "No test sends yet. Fire one above and it lands here."}
              </div>
            ) : log.map((e, i) => {
              const tpl = TEMPLATES.find((t) => t.id === e.newsletter_id) || TEMPLATES[0];
              const res = e.result || "ok";
              return (
                <div key={`${e.at}-${i}`} className="nl-log-row">
                  <span className="nl-log-when">{formatWhen(e.at)}</span>
                  <span className="nl-log-main">
                    <b>{tpl.title}</b> → {e.to}
                    <span className="nl-log-sub"> · {(e.locale || "en").toUpperCase()} · {e.by || "—"}{e.detail ? ` · ${e.detail}` : ""}</span>
                  </span>
                  {/* i18n-allow: admin-only delivery-log status enum (operator console, not a user-facing surface) */}
                  <span className={`nl-res ${res}`}>{res.replace("_", "-")}</span>
                </div>
              );
            })}
          </div>
        </section>

      </div>
    </>
  );
}
