// NewsletterWidget — admin preview trigger.
//
// One email input + one button. Pressing the button asks
// /api/admin/newsletter/trigger-preview to dispatch the `pulpo-newsletter`
// GitHub Actions workflow with `preview_cohorts=<email>`. The workflow
// runs the production Python pipeline end-to-end and sends ONE real
// email — the Pro-with-prefs variant — so the operator can vet what a
// real Pro subscriber sees before flipping send_mode=yes on the real
// audience.
//
// PR-NL-9 (audience scope): the personalised newsletter is a Pro
// feature. The free + anonymous preview variants we used to send are
// gone — Free users will get a different product on a separate
// pipeline; anonymous subscribers are not part of this audience.
//
// Subject is prefixed `[PULPO PREVIEW · pro_prefs]` so the test
// email is unambiguously not a real audience send.
//
// Why we don't preview / send inline in the admin UI: the production
// renderer is Python. Routing through the workflow guarantees the
// preview matches what real subscribers receive byte-for-byte. The
// 30–60s lag for the workflow to spin up is acceptable for an
// iteration-level QA loop — the iteration itself happens in code, not
// in this widget.
//
// Auth: deliberately none on this endpoint beyond rate-limiting. The
// real security perimeter is GITHUB_DISPATCH_TOKEN (fine-grained PAT,
// actions:write on this repo only). Worst-case abuse is preview-
// subjected email spam capped at 15 emails/hr/IP. The bearer-token
// gate was removed after the env-var friction kept blocking the
// operator every iteration — see api/admin/newsletter/trigger-preview.js.

import React, { useState, useEffect, useCallback } from "react";

const DEFAULT_EMAIL = "javier@suarez.ventures";
const DEFAULT_LOCALE = "en";
const LOCALE_OPTIONS = [
  { value: "en", label: "EN" },
  { value: "es", label: "ES" },
];
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Mirrors `synthesize_preview_recipients(email)` in
// automation/newsletter/subscribers.py — kept here as an array (not a
// scalar) so the rendering loop in the success card stays identical if
// we ever add cohorts back. Today it's exactly one: pro_prefs.
const PREVIEW_COHORTS = ["pro_prefs"];

// ── Newsletter registry ────────────────────────────────────────────
// One row per newsletter Pulpo publishes (or plans to). The widget
// renders tier sections (PRO / FREE) and cards from this list — adding
// a new newsletter once it ships is a one-row patch here plus enabling
// `status: "live"`. The matching server allow-list lives in
// `api/admin/newsletter/trigger-preview.js :: KNOWN_NEWSLETTER_IDS`;
// keep them in lock-step.
//
//   id            stable PostHog event key + closed-set allow-list value
//   tier          "pro" | "free" — drives section assignment + log pill
//   title         card heading shown in the chrome
//   description   one-line subhead under the title
//   cadenceMode   "scheduled" (shows the 3-row Upcoming sends list) |
//                 "onetime"   (single trigger row — welcome-style)
//   status        "live" (card renders the trigger UI) |
//                 "coming-soon" (card renders disabled with a tag)
//   template      stable template id (matches the Python composition
//                 function on the renderer side — kept in lock-step)
//   templateLabel human-readable template name shown on the card
//                 chrome ("TEMPLATE · Pulpo Pro General"). When a
//                 new template ships (e.g. "Pulpo Pro Welcome"), the
//                 corresponding newsletter row swaps to that template.
//
// `cadenceMode` is wired today only for "scheduled". When the welcome
// newsletters ship we'll add the "onetime" body next to the existing
// upcoming-list renderer.
//
// All four newsletters currently reference the SAME template
// ("pulpo-pro-general") since it's the only one that exists. Each
// newsletter will swap to its own template when that template lands
// (e.g. Pro Welcome → "pulpo-pro-welcome"). The label is what the
// operator sees on the card chrome.
const NEWSLETTERS = [
  {
    id: "pro-weekly",
    tier: "pro",
    title: "Pro · Weekly digest",
    description: "Sundays 9 AM · 10 curated picks per recipient, personalised to their discover_filters.",
    template: "pulpo-pro-general",
    templateLabel: "Pulpo Pro General",
    cadenceMode: "scheduled",
    status: "live",
  },
  {
    id: "pro-welcome",
    tier: "pro",
    title: "Pro · Welcome",
    description: "Single onboarding email sent when a Free user upgrades to Pro. Lands ~30s after the Stripe checkout completes.",
    template: "pulpo-pro-general",
    templateLabel: "Pulpo Pro General",
    cadenceMode: "onetime",
    status: "coming-soon",
  },
  {
    id: "free-welcome",
    tier: "free",
    title: "Free · Welcome",
    description: "Sent once when an anonymous email subscribes via the homepage form. Sets the audience expectation and surfaces a Pro upgrade CTA.",
    template: "pulpo-pro-general",
    templateLabel: "Pulpo Pro General",
    cadenceMode: "onetime",
    status: "coming-soon",
  },
  {
    id: "free-weekly",
    tier: "free",
    title: "Free · Weekly",
    description: "Lightweight Free-tier digest. Same Sunday cadence as Pro, fewer picks, no personalisation, upgrade nudge baked in.",
    template: "pulpo-pro-general",
    templateLabel: "Pulpo Pro General",
    cadenceMode: "scheduled",
    status: "coming-soon",
  },
];

// v4.3 (2026-05-31) — surface the locked template's version + last
// revision date on every newsletter card. The values here are the
// human-readable form of `TEMPLATE_VERSION` + `LAST_UPDATED` in
// `automation/newsletter/components/_common.py`. The Python-side
// values are the source of truth; this map mirrors them for display.
// `tests/newsletter/test_templates.py::test_template_version_in_widget_matches_python`
// enforces alignment in CI — if the operator bumps TEMPLATE_VERSION
// in Python but forgets to bump this map (or vice versa), CI fails.
const TEMPLATE_VERSIONS = {
  "pulpo-pro-general": { version: "v4.3", lastUpdated: "2026-05-31" },
};

const PRO_NEWSLETTERS = NEWSLETTERS.filter((n) => n.tier === "pro");
const FREE_NEWSLETTERS = NEWSLETTERS.filter((n) => n.tier === "free");

// Look up the registry row for a given id. Pre-registry log rows from
// before the rollout have `newsletter_id == null` — the log renders
// those as Pro · Weekly (the only newsletter that existed before this
// rollout, so attribution is correct).
function newsletterForId(id) {
  return NEWSLETTERS.find((n) => n.id === id) || NEWSLETTERS[0];
}

const WIDGET_STYLES = `
.nl-preview-widget {
  /* Was a single column at 560px. The tier-section layout needs
     more width so the "Send test" + "Send to everyone" buttons stay
     on one row inside each upcoming-send row at 980px container width. */
  max-width: 760px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
/* ── Tier sections (PRO / FREE) ─────────────────────────────────── */
.nl-preview-widget .nl-tier-section {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.nl-preview-widget .nl-tier-header {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin: 12px 0 2px;
}
.nl-preview-widget .nl-tier-header hr {
  flex: 1;
  border: 0;
  border-top: 1px solid var(--line-2);
  margin: 0;
}
.nl-preview-widget .nl-tier-label {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
}
.nl-preview-widget .nl-tier-label.pro {
  background: var(--accent-strong);
  color: var(--paper);
}
.nl-preview-widget .nl-tier-label.free {
  background: var(--paper-3);
  color: var(--ink-2);
}
.nl-preview-widget .nl-tier-count {
  font-size: 12px;
  color: var(--ink-3);
}
/* ── Per-newsletter card (head + body) ──────────────────────────── */
.nl-preview-widget .nl-newsletter-card {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
}
.nl-preview-widget .nl-newsletter-card.coming-soon { opacity: 0.7; }
.nl-preview-widget .nl-newsletter-head {
  padding: 14px 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid var(--line);
}
.nl-preview-widget .nl-newsletter-card.coming-soon .nl-newsletter-head {
  border-bottom-color: transparent;
}
.nl-preview-widget .nl-newsletter-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}
.nl-preview-widget .nl-newsletter-status {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
}
.nl-preview-widget .nl-newsletter-status.live {
  background: var(--accent-soft);
  color: var(--accent-strong);
}
.nl-preview-widget .nl-newsletter-status.coming-soon {
  background: var(--paper-3);
  color: var(--ink-3);
}
.nl-preview-widget .nl-newsletter-desc {
  padding: 10px 18px 8px;
  font-size: 13px;
  color: var(--ink-3);
  line-height: 1.5;
  margin: 0;
}
/* Template label row — small caps badge + optional hint, sits under
   the description so every card is self-describing about which
   renderer template it uses. When a future newsletter swaps templates
   (e.g. Pro Welcome → Pulpo Pro Welcome), this line is where the
   operator sees that. The hint after the dot only shows on live
   newsletters where a test send is actually possible. */
.nl-preview-widget .nl-newsletter-template {
  padding: 0 18px 14px;
  margin: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.10em;
  color: var(--ink-3);
  line-height: 1.5;
  text-transform: uppercase;
  font-weight: 600;
}
.nl-preview-widget .nl-newsletter-template strong {
  color: var(--ink-2);
  font-weight: 700;
}
.nl-preview-widget .nl-newsletter-template .nl-newsletter-template-hint {
  letter-spacing: 0;
  text-transform: none;
  font-weight: 500;
  color: var(--ink-3);
  font-family: var(--font-sans);
  font-size: 12px;
}
.nl-preview-widget .nl-newsletter-body {
  padding: 0 18px 16px;
}
.nl-preview-widget .nl-newsletter-card.coming-soon .nl-newsletter-body {
  display: none;
}
/* Existing .nl-card primitive retained below for back-compat (used by
   the shared controls bar). */

.nl-preview-widget .nl-card {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.nl-preview-widget label {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-3);
}
.nl-preview-widget input[type=email] {
  font: inherit;
  padding: 10px 12px;
  border: 1px solid var(--line-2);
  border-radius: 6px;
  background: var(--paper);
  color: var(--ink);
  width: 100%;
}
.nl-preview-widget input[type=email]:focus {
  outline: 2px solid var(--accent);
  outline-offset: -1px;
}
/* The nl-trigger class styled the bottom submit button — removed
   alongside the button itself. The per-row "Send test" buttons in
   Upcoming Sends use .nl-upcoming-btn (defined further down). */

.nl-preview-widget .nl-hint {
  font-size: 13px;
  line-height: 19px;
  color: var(--ink-3);
  margin: 0;
}
.nl-preview-widget .nl-hint code {
  font-family: var(--font-mono);
  font-size: 12px;
  background: var(--paper-2);
  padding: 1px 4px;
  border-radius: 3px;
}

/* ── status: success → structured card ────────────────────────────── */
.nl-preview-widget .nl-success {
  margin: 4px 0 0;
  background: var(--paper-2);
  border: 1px solid var(--line-2);
  border-left: 3px solid var(--accent-strong);
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.nl-preview-widget .nl-success-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
  margin: 0;
}
.nl-preview-widget .nl-success-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 999px;
  background: var(--accent-strong);
  color: var(--paper);
  font-size: 11px;
  line-height: 1;
  flex: 0 0 auto;
}
.nl-preview-widget .nl-success-body {
  font-size: 13px;
  line-height: 19px;
  color: var(--ink-2);
  margin: 0;
}
.nl-preview-widget .nl-success-body strong { color: var(--ink); }
.nl-preview-widget .nl-success-subjects {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.nl-preview-widget .nl-success-subjects li {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 18px;
  color: var(--ink-2);
  padding: 4px 8px;
  background: var(--paper);
  border: 1px solid var(--line-2);
  border-radius: 4px;
  overflow-wrap: anywhere;
}
.nl-preview-widget .nl-success-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  margin: 2px 0 0;
}
.nl-preview-widget .nl-success-footer a {
  color: var(--accent-strong);
  text-decoration: none;
  font-weight: 600;
}
.nl-preview-widget .nl-success-footer a:hover { text-decoration: underline; }

/* ── status: error / pending → single inline line ─────────────────── */
.nl-preview-widget .nl-status {
  font-size: 13px;
  line-height: 19px;
  margin: 4px 0 0;
  min-height: 18px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.nl-preview-widget .nl-status.error {
  color: var(--badge-drop);
}
.nl-preview-widget .nl-status.pending {
  color: var(--ink-3);
}
.nl-preview-widget .nl-status .nl-status-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  font-size: 10px;
  line-height: 1;
  flex: 0 0 auto;
}
.nl-preview-widget .nl-status.error .nl-status-icon {
  background: var(--badge-drop);
  color: var(--paper);
}
.nl-preview-widget .nl-status.pending .nl-status-icon {
  border: 2px solid var(--line-2);
  border-top-color: var(--ink-3);
  animation: nl-spin 800ms linear infinite;
}
@keyframes nl-spin { to { transform: rotate(360deg); } }

/* ── Locale toggle (EN | ES) ──────────────────────────────────────── */
.nl-preview-widget .nl-locale {
  display: flex;
  align-items: center;
  gap: 8px;
}
.nl-preview-widget .nl-locale-toggle {
  display: inline-flex;
  border: 1px solid var(--line-2);
  border-radius: 6px;
  overflow: hidden;
  background: var(--paper);
}
.nl-preview-widget .nl-locale-btn {
  appearance: none;
  background: transparent;
  border: 0;
  font: inherit;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  padding: 6px 14px;
  color: var(--ink-3);
  cursor: pointer;
}
.nl-preview-widget .nl-locale-btn + .nl-locale-btn {
  border-left: 1px solid var(--line-2);
}
.nl-preview-widget .nl-locale-btn[aria-pressed="true"] {
  background: var(--ink);
  color: var(--paper);
}
.nl-preview-widget .nl-locale-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

/* ── PR-NL-7a · Upcoming sends panel ────────────────────────────── */
.nl-preview-widget .nl-upcoming {
  margin: 4px 0 0;
  padding: 14px 16px 12px;
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.nl-preview-widget .nl-upcoming-eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin: 0 0 10px;
  font-weight: 600;
}
.nl-preview-widget .nl-upcoming-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.nl-preview-widget .nl-upcoming-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 10px;
  background: var(--paper);
  border: 1px solid var(--line-2);
  border-radius: 6px;
}
.nl-preview-widget .nl-upcoming-row-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.nl-preview-widget .nl-upcoming-row .nl-upcoming-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.nl-preview-widget .nl-upcoming-row .nl-upcoming-issue {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}
.nl-preview-widget .nl-upcoming-row .nl-upcoming-when {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-3);
}
.nl-preview-widget .nl-upcoming-actions {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
  align-items: center;
}
.nl-preview-widget .nl-upcoming-btn,
.nl-preview-widget .nl-audience-btn {
  background: transparent;
  color: var(--ink);
  border: 1px solid var(--line-2);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}
.nl-preview-widget .nl-upcoming-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.nl-preview-widget .nl-audience-btn {
  /* Audience send is the high-blast-radius action — use a deliberate
     warm tone (clay border) so the button doesn't look like just
     another "Send test" sibling. Type-to-confirm gate sits behind it. */
  border-color: var(--clay, #B8643C);
  color: var(--clay, #B8643C);
}
.nl-preview-widget .nl-audience-btn:hover {
  background: var(--clay, #B8643C);
  color: #fff;
}
.nl-preview-widget .nl-upcoming-btn[disabled],
.nl-preview-widget .nl-audience-btn[disabled] {
  opacity: 0.45;
  cursor: not-allowed;
}
/* ── Audience-send inline confirmation ─────────────────────────────
   Drops in below the row when the operator clicks "Send to everyone".
   Type-to-confirm input + Cancel/Send buttons. Server-side mirror of
   the SEND gate at /api/admin/newsletter/trigger-audience-send. */
.nl-preview-widget .nl-audience-confirm {
  margin-top: 4px;
  padding: 14px;
  background: #FFF8F0;
  border: 1px solid var(--clay, #B8643C);
  border-radius: 6px;
}
.nl-preview-widget .nl-audience-headline {
  margin: 0 0 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}
.nl-preview-widget .nl-audience-headline.ok { color: #1F3D31; }
.nl-preview-widget .nl-audience-headline.err { color: #6B2C2C; }
.nl-preview-widget .nl-audience-warn,
.nl-preview-widget .nl-audience-body {
  margin: 4px 0 10px;
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.5;
}
.nl-preview-widget .nl-audience-confirm-label {
  display: block;
  font-size: 12px;
  color: var(--ink-2);
  margin-bottom: 10px;
}
.nl-preview-widget .nl-audience-confirm-input {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 8px 10px;
  font: inherit;
  font-size: 14px;
  font-family: var(--font-mono, monospace);
  border: 1px solid var(--line-2);
  border-radius: 4px;
  letter-spacing: 0.08em;
}
.nl-preview-widget .nl-audience-confirm-input:focus {
  outline: 2px solid var(--clay, #B8643C);
  outline-offset: 1px;
}
.nl-preview-widget .nl-audience-confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
.nl-preview-widget .nl-audience-cancel {
  background: transparent;
  color: var(--ink-2);
  border: 1px solid var(--line-2);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
}
.nl-preview-widget .nl-audience-send {
  background: var(--clay, #B8643C);
  color: #fff;
  border: 1px solid var(--clay, #B8643C);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
}
.nl-preview-widget .nl-audience-send[disabled] {
  background: #ccc;
  border-color: #ccc;
  cursor: not-allowed;
}
.nl-preview-widget .nl-audience-loading {
  margin: 0;
  font-size: 13px;
  color: var(--ink-2);
}
/* ── Recent test sends log ─────────────────────────────────────────
   Per-browser localStorage log of trigger attempts. Lives below the
   Upcoming sends panel so the operator can see whether the last test
   actually fired without flipping to Gmail or PostHog. Persistence is
   browser-scoped — operators on a fresh laptop start with an empty
   log. Cross-device history is a follow-up. */
.nl-preview-widget .nl-log {
  margin-top: 10px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.nl-preview-widget .nl-log-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}
.nl-preview-widget .nl-log-eyebrow {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin: 0;
}
.nl-preview-widget .nl-log-clear {
  margin-left: auto;
  background: transparent;
  border: 0;
  font: inherit;
  font-size: 11px;
  color: var(--ink-3);
  cursor: pointer;
  padding: 0;
}
.nl-preview-widget .nl-log-clear:hover { color: var(--ink); }
.nl-preview-widget .nl-log-empty {
  font-size: 12px;
  color: var(--ink-3);
  margin: 0;
}
.nl-preview-widget .nl-log-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  table-layout: fixed;
}
.nl-preview-widget .nl-log-table th,
.nl-preview-widget .nl-log-table td {
  text-align: left;
  padding: 6px 8px 6px 0;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nl-preview-widget .nl-log-table th {
  font-size: 10px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  color: var(--ink-3);
  font-weight: 600;
  border-bottom-color: var(--line-2);
}
.nl-preview-widget .nl-log-table tr:last-child td { border-bottom: 0; }
.nl-preview-widget .nl-log-when { width: 14%; color: var(--ink-3); font-family: var(--font-mono); font-size: 11px; }
.nl-preview-widget .nl-log-newsletter { width: 22%; }
.nl-preview-widget .nl-log-newsletter .nl-log-pill {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 9.5px;
  font-family: var(--font-mono);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-weight: 700;
  margin-right: 6px;
  vertical-align: 1px;
}
.nl-preview-widget .nl-log-newsletter .nl-log-pill.pro {
  background: var(--accent-soft);
  color: var(--accent-strong);
}
.nl-preview-widget .nl-log-newsletter .nl-log-pill.free {
  background: var(--paper-3);
  color: var(--ink-2);
}
.nl-preview-widget .nl-log-to { width: 22%; color: var(--ink); }
.nl-preview-widget .nl-log-locale { width: 6%; font-family: var(--font-mono); font-size: 11px; color: var(--ink-3); text-transform: uppercase; }
.nl-preview-widget .nl-log-by { width: 22%; color: var(--ink-3); }
.nl-preview-widget .nl-log-result { width: 14%; font-weight: 600; }
.nl-preview-widget .nl-log-result.ok { color: var(--accent); }
.nl-preview-widget .nl-log-result.err { color: oklch(55% 0.18 25); }
`;

// PR-NL-7a — next-Monday helper. Cron runs every Mon 14:00 UTC; we
// just enumerate the next N Mondays from "now" in the operator's local
// timezone so the displayed date matches what they expect. Issue
// numbers are inferred from the same source-of-truth in build_issue.py
// — falling back to a "next / +2 weeks / +4 weeks" framing when no
// concrete number is plumbed yet (PR-NL-9 will wire the real number).
function nextMondays(count = 3, from = new Date()) {
  const out = [];
  const base = new Date(from);
  base.setHours(0, 0, 0, 0);
  // 0 = Sunday … 1 = Monday … 6 = Saturday
  const daysUntilMon = (1 - base.getDay() + 7) % 7 || 7;
  const next = new Date(base);
  next.setDate(base.getDate() + daysUntilMon);
  for (let i = 0; i < count; i++) {
    const d = new Date(next);
    d.setDate(next.getDate() + i * 7);
    out.push(d);
  }
  return out;
}

function formatMondayLabel(d, now = new Date()) {
  const dayMs = 24 * 60 * 60 * 1000;
  const today = new Date(now); today.setHours(0, 0, 0, 0);
  const days = Math.round((d.getTime() - today.getTime()) / dayMs);
  const dateStr = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const inLabel = days <= 0 ? "today"
    : days === 1 ? "tomorrow"
    : days < 14 ? `in ${days} days`
    : `in ${Math.round(days / 7)} weeks`;
  return `${dateStr} · ${inLabel}`;
}

// ── Recent test sends log ────────────────────────────────────────────
// Per-browser localStorage log of trigger attempts. Keys + helpers live
// at module scope so a future operator surface (e.g. an admin export
// button) can reuse them. Cap at LOG_CAP so the row never grows
// unbounded; oldest entries fall off first.
const LOG_LS_KEY = "pulpo-admin-newsletter-trigger-log";
const LOG_CAP = 20;

function readLog() {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(LOG_LS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
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
    // localStorage quota / private-mode failures are silent — the
    // log is a UX convenience, not a contract.
  }
}

function appendLogEntry(entry) {
  const next = [entry, ...readLog()];
  writeLog(next);
  return next;
}

// Operator identity for the "By" column. /admin is Clerk-gated so a
// session is guaranteed to exist by the time a trigger fires — we read
// it off the same `pulpo-user` localStorage blob app.jsx writes (see
// app.jsx :: setUser localStorage mirror). Falls back to "—" if the
// blob is missing or malformed (legacy auth path, dev without Clerk).
function readOperatorEmail() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem("pulpo-user");
    if (!raw) return null;
    const u = JSON.parse(raw);
    return typeof u?.email === "string" ? u.email : null;
  } catch {
    return null;
  }
}

// Cross-device log: fetched from /api/admin/newsletter/recent-triggers
// which queries PostHog HogQL server-side. Merges with the local
// localStorage log so the operator sees their own just-fired test
// instantly (PostHog ingestion has ~1-5s latency before the event
// shows up in a HogQL query). Dedupe by the `at` timestamp — both
// sources write ISO strings produced within the same trigger call.
async function fetchServerLog() {
  if (typeof window === "undefined") return { events: [], unavailable_reason: null };
  try {
    const r = await fetch("/api/admin/newsletter/recent-triggers", {
      method: "GET",
      headers: { "accept": "application/json" },
    });
    if (!r.ok) return { events: [], unavailable_reason: `HTTP ${r.status}` };
    const body = await r.json().catch(() => null);
    return {
      events: Array.isArray(body?.events) ? body.events : [],
      unavailable_reason: typeof body?.unavailable_reason === "string"
        ? body.unavailable_reason
        : null,
    };
  } catch (err) {
    return { events: [], unavailable_reason: String(err && err.message || err) };
  }
}

function mergeLogs(serverEvents, localEvents) {
  // Both sources produce ISO timestamps in the `at` field. Server
  // wins on duplicates (it's the canonical record once PostHog has
  // ingested); local stays for entries the server hasn't seen yet.
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
  // Resort by timestamp DESC — server returns DESC but the merge order
  // depends on whichever side had the entry first.
  out.sort((a, b) => (b.at || "").localeCompare(a.at || ""));
  return out.slice(0, LOG_CAP);
}

// Compact "5 min ago" / "Wed 30 May, 10:43" formatter. Recent rows
// stay relative so the operator can scan latency at a glance; rows
// older than ~6 hours flip to absolute so the log still reads after
// returning the next day.
function formatLogWhen(iso, now = new Date()) {
  const t = new Date(iso);
  const diffMs = now.getTime() - t.getTime();
  const min = Math.round(diffMs / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 6) return `${hr} h ago`;
  return t.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}


export function NewsletterWidget() {
  const [email, setEmail] = useState(DEFAULT_EMAIL);
  const [locale, setLocale] = useState(DEFAULT_LOCALE);
  const [busy, setBusy] = useState(false);
  // statusByNewsletterId — per-card status, so the success/pending/
  // error confirmation lands INSIDE the card the operator triggered
  // from instead of at the bottom of the page (operator feedback
  // 2026-05-31: the global block was easy to miss without scrolling).
  // Shape: { [newsletterId]: { kind, message?, recipient?, runsUrl?, when? } }
  // Each entry is the same discriminated union by `kind` as v3's
  // single `status` state:
  //   { kind: null }                            — nothing rendered
  //   { kind: "pending" }                       — spinner + "Dispatching…"
  //   { kind: "error",   message }              — red inline line
  //   { kind: "success", recipient, runsUrl }   — structured success card
  const [statusByNewsletterId, setStatusByNewsletterId] = useState({});
  const setStatusFor = useCallback((newsletterId, next) => {
    setStatusByNewsletterId((prev) => ({ ...prev, [newsletterId]: next }));
  }, []);
  const statusFor = (newsletterId) => statusByNewsletterId[newsletterId] || { kind: null };
  // Per-browser localStorage log of trigger attempts. Hydrates from
  // localStorage on mount so the log survives a reload.
  const [localEntries, setLocalEntries] = useState(() => readLog());
  // Server-side cross-device log via /api/admin/newsletter/recent-triggers
  // (PostHog HogQL). Fetched on mount + after every trigger. Falls back
  // to "" when POSTHOG_PERSONAL_API_KEY / POSTHOG_PROJECT_ID env vars
  // are missing in Vercel — the response body's `unavailable_reason`
  // tells the operator why the cross-device view is empty.
  const [serverEntries, setServerEntries] = useState([]);
  const [serverUnavailable, setServerUnavailable] = useState(null);
  const refreshServerLog = useCallback(async () => {
    const { events, unavailable_reason } = await fetchServerLog();
    setServerEntries(events);
    setServerUnavailable(unavailable_reason);
  }, []);
  useEffect(() => {
    refreshServerLog();
  }, [refreshServerLog]);
  // Merged + capped log for rendering. Re-derived on every change of
  // either source — both are tiny arrays so the cost is negligible.
  const log = mergeLogs(serverEntries, localEntries);

  // Upcoming Monday cron date — only the next one. Operator feedback
  // (2026-05-30): the 3-row preview was clutter; only the very next
  // issue is what gets tested or sent ad-hoc. `nextMondays` returns
  // an array so the existing `.map(...)` renderer keeps working
  // unchanged — it just iterates a 1-element list.
  const upcoming = nextMondays(1);

  // ── Audience-send (per-row inline confirmation) ─────────────────
  //
  // The "Send to everyone" button next to each upcoming row fires a
  // LIVE send to every Pro/Agency subscriber. The flow:
  //
  //   1. Operator clicks "Send to everyone".
  //   2. `audienceConfirm` opens for that row + we GET
  //      /api/admin/newsletter/audience-count to populate the count.
  //   3. The inline card shows "Send Issue N to X readers?" + a
  //      type-to-confirm input.
  //   4. Operator types SEND + clicks Send → POST
  //      /api/admin/newsletter/trigger-audience-send.
  //   5. On success: row's audienceConfirm transitions to "dispatched"
  //      with a link to the workflow run.
  //
  // State shape (null = no row in confirm mode; only one at a time):
  //   {
  //     issueNumber: number,
  //     phase: "loading_count" | "ready" | "submitting" | "dispatched" | "error",
  //     typedConfirm: string,         // what's in the input
  //     audienceCount: number | null, // populated after step 2
  //     runsUrl: string | null,       // populated after step 5
  //     errorMessage: string | null,
  //   }
  const [audienceConfirm, setAudienceConfirm] = useState(null);

  const openAudienceConfirm = useCallback(async (issueNumber) => {
    setAudienceConfirm({
      issueNumber,
      phase: "loading_count",
      typedConfirm: "",
      audienceCount: null,
      runsUrl: null,
      errorMessage: null,
    });
    try {
      const r = await fetch("/api/admin/newsletter/audience-count");
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setAudienceConfirm((prev) => prev && prev.issueNumber === issueNumber ? {
          ...prev,
          phase: "error",
          errorMessage: body.error || `Couldn't load audience count (HTTP ${r.status})`,
        } : prev);
        return;
      }
      setAudienceConfirm((prev) => prev && prev.issueNumber === issueNumber ? {
        ...prev,
        phase: "ready",
        audienceCount: typeof body.count === "number" ? body.count : 0,
      } : prev);
    } catch (err) {
      const msg = String(err && err.message || err);
      setAudienceConfirm((prev) => prev && prev.issueNumber === issueNumber ? {
        ...prev,
        phase: "error",
        errorMessage: msg,
      } : prev);
    }
  }, []);

  const cancelAudienceConfirm = useCallback(() => {
    setAudienceConfirm(null);
  }, []);

  const submitAudienceConfirm = useCallback(async () => {
    setAudienceConfirm((prev) => prev ? { ...prev, phase: "submitting", errorMessage: null } : prev);
    const operatorEmail = readOperatorEmail();
    const snapshot = audienceConfirm;
    if (!snapshot) return;
    try {
      const r = await fetch("/api/admin/newsletter/trigger-audience-send", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          confirm: snapshot.typedConfirm,
          issue_number: snapshot.issueNumber,
          audience_count: snapshot.audienceCount,
          by: operatorEmail || undefined,
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const detail = body.error || `HTTP ${r.status}`;
        const hint = body.hint ? ` — ${body.hint}` : "";
        setAudienceConfirm((prev) => prev ? {
          ...prev,
          phase: "error",
          errorMessage: `${detail}${hint}`,
        } : prev);
        return;
      }
      setAudienceConfirm((prev) => prev ? {
        ...prev,
        phase: "dispatched",
        runsUrl: body.runs_url_hint || null,
      } : prev);
      // Refresh the server-side log so the audience send shows up in
      // "Recent test sends" — uses the same PostHog ingestion path.
      window.setTimeout(() => { refreshServerLog(); }, 5000);
    } catch (err) {
      const msg = String(err && err.message || err);
      setAudienceConfirm((prev) => prev ? {
        ...prev,
        phase: "error",
        errorMessage: msg,
      } : prev);
    }
  }, [audienceConfirm, refreshServerLog]);

  // Shared trigger for the per-row "Send test →" buttons in the
  // Upcoming Sends panel. `issueNumber=null` keeps the legacy default
  // ("1" server-side). `newsletterId` defaults to "pro-weekly" for
  // back-compat with callers that don't thread it (today every live
  // trigger is Pro Weekly — Pro Welcome / Free Weekly will pass their
  // own IDs when they ship; the server allow-list already accepts them).
  const trigger = async ({ issueNumber = null, when = null, newsletterId = "pro-weekly" } = {}) => {
    const value = email.trim().toLowerCase();
    if (!value || !EMAIL_RE.test(value)) {
      setStatusFor(newsletterId, { kind: "error", message: "Enter a valid email address." });
      return;
    }
    setBusy(true);
    setStatusFor(newsletterId, { kind: "pending", when });
    const operatorEmail = readOperatorEmail();
    try {
      // `by` lets the server-side audit trail attribute the dispatch
      // to a specific operator on the cross-device log. Spoofable
      // (the endpoint is intentionally auth-light) but useful for
      // the legitimate-traffic happy path.
      const payload = { email: value, locale, by: operatorEmail || undefined, newsletter_id: newsletterId };
      if (issueNumber != null) payload.issue_number = issueNumber;
      const r = await fetch("/api/admin/newsletter/trigger-preview", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json().catch(() => ({}));
      const baseEntry = {
        at: new Date().toISOString(),
        to: value,
        locale,
        by: operatorEmail,
        newsletter_id: newsletterId,
      };
      if (!r.ok) {
        const detail = body.error || `HTTP ${r.status}`;
        const hint = body.hint ? ` — ${body.hint}` : "";
        setStatusFor(newsletterId, { kind: "error", message: `${detail}${hint}` });
        setLocalEntries(appendLogEntry({ ...baseEntry, result: "error", detail: `${detail}${hint}` }));
        return;
      }
      setStatusFor(newsletterId, {
        kind: "success",
        recipient: value,
        runsUrl: body.runs_url || null,
        when,
      });
      setLocalEntries(appendLogEntry({ ...baseEntry, result: "ok" }));
    } catch (err) {
      const msg = String(err && err.message || err);
      setStatusFor(newsletterId, { kind: "error", message: msg });
      setLocalEntries(appendLogEntry({
        at: new Date().toISOString(),
        to: value,
        locale,
        by: operatorEmail,
        newsletter_id: newsletterId,
        result: "error",
        detail: msg,
      }));
    } finally {
      setBusy(false);
      // PostHog ingestion has 1-5s latency before the event lands in
      // a HogQL query result. Refresh after 5s so the just-fired
      // entry promotes from "local-only" to "server-canonical" on
      // its own (the merge dedupes by `at` so there's no flicker).
      window.setTimeout(() => { refreshServerLog(); }, 5000);
    }
  };

  // Clear only wipes the per-browser localStorage layer. The
  // server-side log (PostHog events) is immutable history — operators
  // shouldn't be able to one-click delete an audit trail from the
  // admin UI. The merged view recomputes immediately.
  const clearLog = () => {
    writeLog([]);
    setLocalEntries([]);
  };

  return (
    <>
      <style>{WIDGET_STYLES}</style>
      <div className="nl-preview-widget">
        {/* Was a <form> with a "Send next 3 cohort variants" submit
            button at the bottom. PR-NL-9 follow-up: the per-row "Send
            test →" buttons in Upcoming Sends are the only triggers, so
            the form wrapper became dead weight. Plain <div> means Enter
            on the email input no longer accidentally fires a preview. */}
        <div className="nl-card">
          <div>
            <label htmlFor="nl-preview-email">Send test to</label>
            <input
              id="nl-preview-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              spellCheck={false}
              required
            />
          </div>

          <div className="nl-locale">
            <label htmlFor="nl-preview-locale-en">Language</label>
            <div className="nl-locale-toggle">
              {LOCALE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  id={`nl-preview-locale-${opt.value}`}
                  type="button"
                  className="nl-locale-btn"
                  aria-pressed={locale === opt.value}
                  onClick={() => setLocale(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* ── PRO section ─────────────────────────────────────── */}
          <div className="nl-tier-section">
            <div className="nl-tier-header">
              <span className="nl-tier-label pro">Pro</span>
              <hr />
              <span className="nl-tier-count">{PRO_NEWSLETTERS.length} newsletters</span>
            </div>

            {/* Pro · Weekly — LIVE. Body wraps the existing Upcoming
                sends panel (test + audience triggers per row). */}
            <article className="nl-newsletter-card">
              <div className="nl-newsletter-head">
                <h3 className="nl-newsletter-title">{NEWSLETTERS.find(n => n.id === "pro-weekly").title}</h3>
                <span className="nl-newsletter-status live">● Live</span>
              </div>
              <p className="nl-newsletter-desc">{NEWSLETTERS.find(n => n.id === "pro-weekly").description}</p>
              <p className="nl-newsletter-template">
                Template · <strong>{NEWSLETTERS.find(n => n.id === "pro-weekly").templateLabel}</strong>
                {TEMPLATE_VERSIONS[NEWSLETTERS.find(n => n.id === "pro-weekly").template] && (
                  <> · {TEMPLATE_VERSIONS[NEWSLETTERS.find(n => n.id === "pro-weekly").template].version} ({TEMPLATE_VERSIONS[NEWSLETTERS.find(n => n.id === "pro-weekly").template].lastUpdated})</>
                )}
                <span className="nl-newsletter-template-hint"> · Trigger test to see it</span>
              </p>
              <div className="nl-newsletter-body">

          {/* PR-NL-7a — Upcoming sends. Per-row test button fires the
              same endpoint with that row's issue_number. The shared
              email input above is the recipient for all of them. */}
          <div className="nl-upcoming">
            <p className="nl-upcoming-eyebrow">Upcoming sends</p>
            <ul className="nl-upcoming-list">
              {upcoming.map((d, idx) => {
                const label = formatMondayLabel(d);
                // Issue numbering: the cron's issue_number is operator-
                // driven (PR-NL-9 will plumb the real next number). Until
                // then we use "next / +2 weeks / +4 weeks" as the human
                // label and a stable sequential number for the API call.
                const humanIssue = idx === 0 ? "Next issue"
                  : idx === 1 ? "Following"
                  : "After that";
                const issueNum = idx + 1;
                const confirmOpen = audienceConfirm && audienceConfirm.issueNumber === issueNum;
                return (
                  <li className="nl-upcoming-row" key={d.toISOString()}>
                    <div className="nl-upcoming-row-main">
                      <div className="nl-upcoming-meta">
                        <span className="nl-upcoming-issue">{humanIssue}</span>
                        <span className="nl-upcoming-when">{label}</span>
                      </div>
                      <div className="nl-upcoming-actions">
                        <button
                          type="button"
                          className="nl-upcoming-btn"
                          disabled={busy || !!audienceConfirm}
                          onClick={() => trigger({ issueNumber: issueNum, when: label, newsletterId: "pro-weekly" })}
                          title="Send a test copy to your email only — no real subscribers receive this." // i18n-allow: admin-only widget, operator surface, never shown to subscribers
                        >
                          Send test →
                        </button>
                        <button
                          type="button"
                          className="nl-audience-btn"
                          disabled={busy || !!audienceConfirm}
                          onClick={() => openAudienceConfirm(issueNum)}
                          title="Send this issue to every paying Pulpo subscriber. Confirmation required." // i18n-allow: admin-only widget, operator surface, never shown to subscribers
                        >
                          Send to everyone
                        </button>
                      </div>
                    </div>
                    {confirmOpen && (
                      <div className="nl-audience-confirm" role="dialog" aria-live="polite">
                        {audienceConfirm.phase === "loading_count" && (
                          <p className="nl-audience-loading">
                            <span className="nl-status-icon" aria-hidden="true" />
                            Counting subscribers…
                          </p>
                        )}
                        {audienceConfirm.phase === "ready" && (
                          <>
                            <p className="nl-audience-headline">
                              Send Issue {issueNum} to <strong>{audienceConfirm.audienceCount} {audienceConfirm.audienceCount === 1 ? "reader" : "readers"}</strong>?
                            </p>
                            <p className="nl-audience-warn">
                              This goes to every paying Pulpo subscriber right now. The email can&rsquo;t be recalled once sent.
                            </p>
                            <label className="nl-audience-confirm-label">
                              Type <strong>SEND</strong> to confirm:
                              <input
                                type="text"
                                className="nl-audience-confirm-input"
                                value={audienceConfirm.typedConfirm}
                                onChange={(e) => setAudienceConfirm((prev) => prev ? { ...prev, typedConfirm: e.target.value } : prev)}
                                autoFocus
                                spellCheck={false}
                                autoComplete="off"
                              />
                            </label>
                            <div className="nl-audience-confirm-actions">
                              <button
                                type="button"
                                className="nl-audience-cancel"
                                onClick={cancelAudienceConfirm}
                              >
                                Cancel
                              </button>
                              <button
                                type="button"
                                className="nl-audience-send"
                                disabled={audienceConfirm.typedConfirm !== "SEND"}
                                onClick={submitAudienceConfirm}
                              >
                                Send now
                              </button>
                            </div>
                          </>
                        )}
                        {audienceConfirm.phase === "submitting" && (
                          <p className="nl-audience-loading">
                            <span className="nl-status-icon" aria-hidden="true" />
                            Dispatching to all subscribers…
                          </p>
                        )}
                        {audienceConfirm.phase === "dispatched" && (
                          <>
                            <p className="nl-audience-headline ok">
                              <span className="nl-success-check" aria-hidden="true">✓</span>
                              Sent Issue {issueNum} to {audienceConfirm.audienceCount} {audienceConfirm.audienceCount === 1 ? "reader" : "readers"}
                            </p>
                            <p className="nl-audience-body">
                              The workflow is dispatching now. Resend deliveries follow as the job runs (~30s–2m).
                            </p>
                            {audienceConfirm.runsUrl && (
                              <p>
                                <a href={audienceConfirm.runsUrl} target="_blank" rel="noreferrer">
                                  View workflow run on GitHub →
                                </a>
                              </p>
                            )}
                            <div className="nl-audience-confirm-actions">
                              <button
                                type="button"
                                className="nl-audience-cancel"
                                onClick={cancelAudienceConfirm}
                              >
                                Close
                              </button>
                            </div>
                          </>
                        )}
                        {audienceConfirm.phase === "error" && (
                          <>
                            <p className="nl-audience-headline err">
                              <span aria-hidden="true">!</span> {audienceConfirm.errorMessage || "Something went wrong."}
                            </p>
                            <div className="nl-audience-confirm-actions">
                              <button
                                type="button"
                                className="nl-audience-cancel"
                                onClick={cancelAudienceConfirm}
                              >
                                Close
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          {/* PR-A (2026-05-31) — per-card test-send confirmation. Lives
              INSIDE the Pro · Weekly card body so the operator sees
              the result without scrolling past the cross-device log
              to find a global status block. Threaded by newsletter
              ID via `statusFor()`. */}
          {statusFor("pro-weekly").kind === "pending" && (
            <p className="nl-status pending" aria-live="polite" style={{ marginTop: "12px" }}>
              <span className="nl-status-icon" aria-hidden="true" />
              Dispatching workflow…
            </p>
          )}
          {statusFor("pro-weekly").kind === "error" && (
            <p className="nl-status error" role="alert" aria-live="polite" style={{ marginTop: "12px" }}>
              <span className="nl-status-icon" aria-hidden="true">!</span>
              {statusFor("pro-weekly").message}
            </p>
          )}
          {statusFor("pro-weekly").kind === "success" && (
            <div className="nl-success" role="status" aria-live="polite" style={{ marginTop: "12px" }}>
              <p className="nl-success-head">
                <span className="nl-success-check" aria-hidden="true">✓</span>
                Dispatched · 1 email on the way
              </p>
              <p className="nl-success-body">
                Sending to <strong>{statusFor("pro-weekly").recipient}</strong>
                {statusFor("pro-weekly").when ? <> — preview of the issue scheduled for <strong>{statusFor("pro-weekly").when}</strong></> : null}.
                Should land in ~30–60 seconds. Look for this subject in your inbox:
              </p>
              <ul className="nl-success-subjects">
                {PREVIEW_COHORTS.map((cohort) => (
                  <li key={cohort}>[PULPO PREVIEW · {cohort}] Issue 01</li>
                ))}
              </ul>
              {statusFor("pro-weekly").runsUrl && (
                <p className="nl-success-footer">
                  <a href={statusFor("pro-weekly").runsUrl} target="_blank" rel="noreferrer">
                    View workflow run on GitHub →
                  </a>
                </p>
              )}
            </div>
          )}

              </div>
            </article>

            {/* Pro · Welcome — COMING SOON */}
            {PRO_NEWSLETTERS.filter((n) => n.id !== "pro-weekly").map((nl) => (
              <article key={nl.id} className="nl-newsletter-card coming-soon">
                <div className="nl-newsletter-head">
                  <h3 className="nl-newsletter-title">{nl.title}</h3>
                  <span className="nl-newsletter-status coming-soon">◌ Coming soon</span>
                </div>
                <p className="nl-newsletter-desc">{nl.description}</p>
                <p className="nl-newsletter-template">
                  Template · <strong>{nl.templateLabel}</strong>
                  {TEMPLATE_VERSIONS[nl.template] && (
                    <> · {TEMPLATE_VERSIONS[nl.template].version} ({TEMPLATE_VERSIONS[nl.template].lastUpdated})</>
                  )}
                </p>
              </article>
            ))}
          </div>

          {/* ── FREE section ────────────────────────────────────── */}
          <div className="nl-tier-section">
            <div className="nl-tier-header">
              <span className="nl-tier-label free">Free</span>
              <hr />
              <span className="nl-tier-count">{FREE_NEWSLETTERS.length} newsletters</span>
            </div>
            {FREE_NEWSLETTERS.map((nl) => (
              <article key={nl.id} className={`nl-newsletter-card ${nl.status === "live" ? "" : "coming-soon"}`}>
                <div className="nl-newsletter-head">
                  <h3 className="nl-newsletter-title">{nl.title}</h3>
                  <span className={`nl-newsletter-status ${nl.status === "live" ? "live" : "coming-soon"}`}>
                    {nl.status === "live" ? "● Live" : "◌ Coming soon"}
                  </span>
                </div>
                <p className="nl-newsletter-desc">{nl.description}</p>
                <p className="nl-newsletter-template">
                  Template · <strong>{nl.templateLabel}</strong>
                  {TEMPLATE_VERSIONS[nl.template] && (
                    <> · {TEMPLATE_VERSIONS[nl.template].version} ({TEMPLATE_VERSIONS[nl.template].lastUpdated})</>
                  )}
                  {nl.status === "live" && (
                    <span className="nl-newsletter-template-hint"> · Trigger test to see it</span>
                  )}
                </p>
              </article>
            ))}
          </div>

          {/* Per-browser log of trigger attempts (localStorage). Cap at
              LOG_CAP rows so the row never grows unbounded. Empty state
              renders a one-liner so the operator knows the panel exists
              before they've fired anything. */}
          <div className="nl-log">
            <div className="nl-log-head">
              <p className="nl-log-eyebrow">Recent test sends</p>
              {log.length > 0 && (
                <button type="button" className="nl-log-clear" onClick={clearLog}>
                  Clear
                </button>
              )}
            </div>
            {log.length === 0 ? (
              <p className="nl-log-empty">
                No test sends yet — try one above.
                {serverUnavailable ? (
                  <>
                    <br />
                    <span style={{ color: "var(--ink-3)", fontSize: "12px" }}>
                      You're only seeing sends from this browser. To see what other operators sent (and to see your own sends on other devices), ask your dev to add <code>POSTHOG_PERSONAL_API_KEY</code> and <code>POSTHOG_PROJECT_ID</code> to Vercel.
                    </span>
                  </>
                ) : null}
              </p>
            ) : (
              <table className="nl-log-table">
                <thead>
                  <tr>
                    <th className="nl-log-when">When</th>
                    <th className="nl-log-newsletter">Newsletter</th>
                    <th className="nl-log-to">To</th>
                    <th className="nl-log-locale">Lang</th>
                    <th className="nl-log-by">By</th>
                    <th className="nl-log-result">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {log.map((entry, idx) => {
                    // Pre-registry events have newsletter_id == null —
                    // attribute those to Pro · Weekly, the only newsletter
                    // that existed before the rollout.
                    const nl = newsletterForId(entry.newsletter_id || "pro-weekly");
                    return (
                      <tr key={`${entry.at}-${idx}`}>
                        <td className="nl-log-when" title={entry.at}>{formatLogWhen(entry.at)}</td>
                        <td className="nl-log-newsletter">
                          <span className={`nl-log-pill ${nl.tier}`}>{nl.tier}</span>
                          {nl.title.replace(/^(Pro|Free)\s*·\s*/, "")}
                        </td>
                        <td className="nl-log-to" title={entry.to}>{entry.to}</td>
                        <td className="nl-log-locale">{entry.locale}</td>
                        <td className="nl-log-by" title={entry.by || ""}>{entry.by || "—"}</td>
                        <td className={`nl-log-result ${entry.result === "ok" ? "ok" : "err"}`} title={entry.detail || ""}>
                          {entry.result === "ok" ? "✓ Sent" : "✗ Failed"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* PR-A (2026-05-31): the global success/pending/error block
              that used to live here is gone — status now renders
              inline UNDER the specific newsletter card that was
              triggered (see the `statusFor(...)` blocks inside each
              card body above). The "Recent test sends" table above
              still gives the cross-device audit log. */}
        </div>
      </div>
    </>
  );
}
