// NewsletterWidget — admin preview trigger.
//
// One email input + one button. Pressing the button asks
// /api/admin/newsletter/trigger-preview to dispatch the `pulpo-newsletter`
// GitHub Actions workflow with `preview_cohorts=<email>`. The workflow
// then runs the production Python pipeline end-to-end and sends three
// real emails — one per cohort variant (anonymous, free_prefs,
// pro_prefs) — so the operator can vet what each subscriber type
// receives before flipping send_mode=yes on the real audience.
//
// Subjects are prefixed `[PULPO PREVIEW · <cohort>]` so the test
// emails are unambiguously not real audience sends.
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
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Mirrors `synthesize_preview_recipients(email)` in
// automation/newsletter/subscribers.py — the operator should see the
// same three cohorts the script will actually generate, so the success
// card's subject preview matches what shows up in their inbox.
const PREVIEW_COHORTS = ["anonymous", "free_prefs", "pro_prefs"];

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
.nl-preview-widget button.nl-trigger {
  appearance: none;
  font: inherit;
  font-weight: 600;
  background: var(--accent);
  color: var(--paper);
  border: 1px solid var(--accent);
  border-radius: 8px;
  padding: 10px 16px;
  cursor: pointer;
  align-self: flex-start;
  transition: background 120ms ease, border-color 120ms ease;
}
.nl-preview-widget button.nl-trigger:hover {
  background: var(--accent-strong);
  border-color: var(--accent-strong);
}
.nl-preview-widget button.nl-trigger[disabled] { opacity: 0.55; cursor: not-allowed; }

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
`;

export function NewsletterWidget() {
  const [email, setEmail] = useState(DEFAULT_EMAIL);
  const [busy, setBusy] = useState(false);
  // status is a discriminated union by `kind`:
  //   { kind: null }                            — nothing rendered
  //   { kind: "pending" }                       — spinner + "Dispatching…"
  //   { kind: "error",   message }              — red inline line
  //   { kind: "success", recipient, runsUrl }   — structured success card
  const [status, setStatus] = useState({ kind: null });

  const trigger = async (e) => {
    e.preventDefault();
    const value = email.trim().toLowerCase();
    if (!value || !EMAIL_RE.test(value)) {
      setStatus({ kind: "error", message: "Enter a valid email address." });
      return;
    }
    setBusy(true);
    setStatus({ kind: "pending" });
    try {
      const r = await fetch("/api/admin/newsletter/trigger-preview", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: value }),
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
        <form className="nl-card" onSubmit={trigger}>
          <div>
            <label htmlFor="nl-preview-email">Preview recipient</label>
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
          <button type="submit" className="nl-trigger" disabled={busy}>
            {busy ? "Dispatching…" : "Send next 3 cohort variants"}
          </button>

          {status.kind === "success" && (
            <div className="nl-success" role="status" aria-live="polite">
              <p className="nl-success-head">
                <span className="nl-success-check" aria-hidden="true">✓</span>
                Dispatched · 3 emails on the way
              </p>
              <p className="nl-success-body">
                Sending to <strong>{status.recipient}</strong>. They should
                land in ~30–60 seconds. Look for these subjects in your inbox:
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
        </form>

        <p className="nl-hint">
          Triggers the <code>pulpo-newsletter</code> GitHub Actions workflow
          with <code>preview_cohorts=&lt;email&gt;</code>. Runs the full
          production Python pipeline and sends three real emails
          (<strong>anonymous</strong>, <strong>free_prefs</strong>,
          {" "}<strong>pro_prefs</strong>) to the address above. Use this
          to vet what each subscriber type receives before flipping
          {" "}<code>send_mode=yes</code> on the real audience. Modify
          content via code, then re-trigger to re-check.
        </p>
      </div>
    </>
  );
}
