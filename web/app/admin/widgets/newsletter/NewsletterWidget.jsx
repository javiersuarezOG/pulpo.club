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
// Auth: /admin is "open by design" (no entry-level gate) but every
// /api/admin/* write endpoint requires `Authorization: Bearer <token>`
// where token == `PULPO_ADMIN_DEBUG_TOKEN` server-side. This widget
// hosts the only UI to set that token (lives in localStorage via
// admin-token.ts). First-time setup: enter the token once per browser;
// the trigger button stays disabled until a token is stored. If the
// server rejects the token (401), adminFetch wipes it and we re-prompt.

import React, { useEffect, useState } from "react";
import {
  adminFetch,
  clearAdminToken,
  hasAdminToken,
  setAdminToken,
} from "../../lib/admin-token.ts";

const DEFAULT_EMAIL = "javier@suarez.ventures";
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

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
.nl-preview-widget input[type=email],
.nl-preview-widget input[type=password] {
  font: inherit;
  padding: 10px 12px;
  border: 1px solid var(--line-2);
  border-radius: 6px;
  background: var(--paper);
  color: var(--ink);
  width: 100%;
}
.nl-preview-widget input:focus {
  outline: 2px solid var(--accent);
  outline-offset: -1px;
}
.nl-preview-widget .nl-token-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--ink-3);
}
.nl-preview-widget .nl-token-row button {
  background: none;
  border: none;
  color: var(--ink-3);
  font: inherit;
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
  align-self: auto;
}
.nl-preview-widget .nl-token-row button:hover { color: var(--accent); }
.nl-preview-widget button {
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
.nl-preview-widget button:hover {
  background: var(--accent-strong);
  border-color: var(--accent-strong);
}
.nl-preview-widget button[disabled] { opacity: 0.55; cursor: not-allowed; }
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
.nl-preview-widget .nl-status {
  font-size: 13px;
  line-height: 19px;
  margin: 0;
  min-height: 18px;
}
.nl-preview-widget .nl-status.error { color: var(--badge-drop); }
.nl-preview-widget .nl-status.success { color: var(--accent-strong); }
.nl-preview-widget .nl-status a { color: inherit; text-decoration: underline; }
`;

export function NewsletterWidget() {
  const [email, setEmail] = useState(DEFAULT_EMAIL);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState({ kind: null, message: "", url: null });

  // Admin bearer token (PULPO_ADMIN_DEBUG_TOKEN on the server side).
  // /admin is "open by design" — no entry-level gate — but every
  // /api/admin/* write endpoint still requires the bearer. The token
  // lives in localStorage; this widget hosts the only UI to set it.
  // adminFetch fires `pulpo:admin-token-invalid` on a 401 (after wiping
  // the stored value), so we re-prompt when that happens.
  const [tokenSet, setTokenSet] = useState(() => hasAdminToken());
  const [tokenDraft, setTokenDraft] = useState("");
  const [editingToken, setEditingToken] = useState(false);

  useEffect(() => {
    const onInvalid = () => {
      setTokenSet(false);
      setEditingToken(true);
      setStatus({
        kind: "error",
        message: "Admin token rejected — re-enter below.",
        url: null,
      });
    };
    window.addEventListener("pulpo:admin-token-invalid", onInvalid);
    return () => window.removeEventListener("pulpo:admin-token-invalid", onInvalid);
  }, []);

  const saveToken = () => {
    const v = tokenDraft.trim();
    if (!v) return;
    setAdminToken(v);
    setTokenSet(true);
    setEditingToken(false);
    setTokenDraft("");
    if (status.kind === "error" && /token/i.test(status.message)) {
      setStatus({ kind: null, message: "", url: null });
    }
  };

  const forgetToken = () => {
    clearAdminToken();
    setTokenSet(false);
    setEditingToken(true);
  };

  const trigger = async (e) => {
    e.preventDefault();
    const value = email.trim().toLowerCase();
    if (!value || !EMAIL_RE.test(value)) {
      setStatus({ kind: "error", message: "Enter a valid email address.", url: null });
      return;
    }
    if (!hasAdminToken()) {
      setTokenSet(false);
      setEditingToken(true);
      setStatus({
        kind: "error",
        message: "Set the admin token first.",
        url: null,
      });
      return;
    }
    setBusy(true);
    setStatus({ kind: null, message: "Dispatching workflow…", url: null });
    try {
      const r = await adminFetch("/api/admin/newsletter/trigger-preview", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: value }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const detail = body.error || `HTTP ${r.status}`;
        const hint = body.hint ? ` — ${body.hint}` : "";
        setStatus({ kind: "error", message: `${detail}${hint}`, url: null });
        return;
      }
      setStatus({
        kind: "success",
        message:
          `Workflow dispatched. Three emails to ${value} arrive in ~30–60s. ` +
          `Subjects prefixed [PULPO PREVIEW · <cohort>].`,
        url: body.runs_url || null,
      });
    } catch (err) {
      setStatus({
        kind: "error",
        message: String(err && err.message || err),
        url: null,
      });
    } finally {
      setBusy(false);
    }
  };

  const showTokenInput = !tokenSet || editingToken;

  return (
    <>
      <style>{WIDGET_STYLES}</style>
      <div className="nl-preview-widget">
        <form className="nl-card" onSubmit={trigger}>
          {showTokenInput ? (
            <div>
              <label htmlFor="nl-admin-token">Admin token</label>
              <input
                id="nl-admin-token"
                type="password"
                value={tokenDraft}
                onChange={(e) => setTokenDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); saveToken(); }
                }}
                onBlur={saveToken}
                placeholder="PULPO_ADMIN_DEBUG_TOKEN value"
                autoComplete="off"
                spellCheck={false}
              />
            </div>
          ) : (
            <div className="nl-token-row">
              <span>Admin token set in this browser.</span>
              <button type="button" onClick={forgetToken}>Forget token</button>
            </div>
          )}

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
          <button type="submit" disabled={busy}>
            {busy ? "Dispatching…" : "Send next 3 cohort variants"}
          </button>
          <p
            className={`nl-status ${status.kind || ""}`}
            role={status.kind === "error" ? "alert" : undefined}
            aria-live="polite"
          >
            {status.message}
            {status.url && (
              <> · <a href={status.url} target="_blank" rel="noreferrer">workflow runs</a></>
            )}
          </p>
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
