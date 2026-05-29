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

import React, { useState } from "react";

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

const WIDGET_STYLES = `
.nl-preview-widget {
  max-width: 560px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
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
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  background: var(--paper);
  border: 1px solid var(--line-2);
  border-radius: 6px;
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
.nl-preview-widget .nl-upcoming-btn {
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
  flex: 0 0 auto;
}
.nl-preview-widget .nl-upcoming-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.nl-preview-widget .nl-upcoming-btn[disabled] {
  opacity: 0.45;
  cursor: not-allowed;
}
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


export function NewsletterWidget() {
  const [email, setEmail] = useState(DEFAULT_EMAIL);
  const [locale, setLocale] = useState(DEFAULT_LOCALE);
  const [busy, setBusy] = useState(false);
  // status is a discriminated union by `kind`:
  //   { kind: null }                            — nothing rendered
  //   { kind: "pending" }                       — spinner + "Dispatching…"
  //   { kind: "error",   message }              — red inline line
  //   { kind: "success", recipient, runsUrl }   — structured success card
  const [status, setStatus] = useState({ kind: null });

  // Upcoming Monday cron dates — computed on every render so the
  // "in N days" label stays correct without an interval-tick state.
  // Cheap (~3 ops), no useMemo needed.
  const upcoming = nextMondays(3);

  // Shared trigger for both the legacy "Send next 3 cohort variants"
  // button and the per-row "Send test →" buttons in the Upcoming Sends
  // panel. `issueNumber=null` keeps the legacy default ("1" server-side).
  const trigger = async ({ issueNumber = null, when = null } = {}) => {
    const value = email.trim().toLowerCase();
    if (!value || !EMAIL_RE.test(value)) {
      setStatus({ kind: "error", message: "Enter a valid email address." });
      return;
    }
    setBusy(true);
    setStatus({ kind: "pending", when });
    try {
      const payload = { email: value, locale };
      if (issueNumber != null) payload.issue_number = issueNumber;
      const r = await fetch("/api/admin/newsletter/trigger-preview", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const detail = body.error || `HTTP ${r.status}`;
        const hint = body.hint ? ` — ${body.hint}` : "";
        setStatus({ kind: "error", message: `${detail}${hint}` });
        return;
      }
      setStatus({
        kind: "success",
        recipient: value,
        runsUrl: body.runs_url || null,
        when,
      });
    } catch (err) {
      setStatus({
        kind: "error",
        message: String(err && err.message || err),
      });
    } finally {
      setBusy(false);
    }
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
            <div
              id="nl-preview-locale"
              className="nl-locale-toggle"
              role="group"
              aria-label="Preview language"
            >
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
                return (
                  <li className="nl-upcoming-row" key={d.toISOString()}>
                    <div className="nl-upcoming-meta">
                      <span className="nl-upcoming-issue">{humanIssue}</span>
                      <span className="nl-upcoming-when">{label}</span>
                    </div>
                    <button
                      type="button"
                      className="nl-upcoming-btn"
                      disabled={busy}
                      onClick={() => trigger({ issueNumber: idx + 1, when: label })}
                    >
                      Send test →
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Bottom submit button removed — the per-row "Send test →"
              buttons in Upcoming Sends cover the same intent without
              forcing the operator to pick between two routes for the
              same action. */}

          {status.kind === "success" && (
            <div className="nl-success" role="status" aria-live="polite">
              <p className="nl-success-head">
                <span className="nl-success-check" aria-hidden="true">✓</span>
                Dispatched · 1 email on the way
              </p>
              <p className="nl-success-body">
                Sending to <strong>{status.recipient}</strong>
                {status.when ? <> — preview of the issue scheduled for <strong>{status.when}</strong></> : null}.
                Should land in ~30–60 seconds. Look for this subject in your inbox:
              </p>
              <ul className="nl-success-subjects">
                {PREVIEW_COHORTS.map((cohort) => (
                  <li key={cohort}>[PULPO PREVIEW · {cohort}] Issue 01</li>
                ))}
              </ul>
              {status.runsUrl && (
                <p className="nl-success-footer">
                  <a href={status.runsUrl} target="_blank" rel="noreferrer">
                    View workflow run on GitHub →
                  </a>
                </p>
              )}
            </div>
          )}

          {status.kind === "pending" && (
            <p className="nl-status pending" aria-live="polite">
              <span className="nl-status-icon" aria-hidden="true" />
              Dispatching workflow…
            </p>
          )}

          {status.kind === "error" && (
            <p className="nl-status error" role="alert" aria-live="polite">
              <span className="nl-status-icon" aria-hidden="true">!</span>
              {status.message}
            </p>
          )}
        </div>
      </div>
    </>
  );
}
