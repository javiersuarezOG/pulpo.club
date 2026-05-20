// NewsletterWidget — first admin tool.
//
// Compose a one-off newsletter from current `web/data/ranked.json`
// listings using any filter combination supported by the production
// pipeline (departments / zones / property types / categories / price
// band / cohort / locale), preview the cut, and send a test email.
//
// Backends:
//   GET  /api/admin/newsletter/options  — dimensions for the form
//   POST /api/admin/newsletter/preview  — filter + render HTML
//   POST /api/admin/newsletter/send     — same + Resend a test email
//
// Send guardrails (enforced server-side, restated here for the operator):
//   - hard cap of 5 recipients per call. No `confirm_broadcast` escape.
//   - subject is tagged `[PULPO ADMIN TEST]` so a misdelivered email is
//     unambiguously not the production newsletter.
//   - audience-wide sends remain in the GitHub Actions workflow_dispatch
//     path (`pulpo-newsletter` workflow with `send_mode=yes`).

import React, { useEffect, useMemo, useState } from "react";

// Default recipient is Javier's address (the admin owner). The form lets
// the user replace or add — but the page never broadcasts.
const DEFAULT_RECIPIENT = "javier@suarez.ventures";
const MAX_RECIPIENTS = 5;

// Mirror of `CATEGORY_PREDICATES` in automation/newsletter/segments.py.
// Kept inline so the UI doesn't have to round-trip to the server for the
// list of available categories — the server still enforces the canonical
// set (mismatches degrade silently to "no opinion" on that axis).
const CATEGORY_OPTIONS = [
  ["beachfront",         "Beachfront or walk-to-beach"],
  ["water_features",     "Has water features (river / lake / sea)"],
  ["ocean_view",         "Ocean view"],
  ["mountain_view",      "Mountain view"],
  ["flat_buildable",     "Flat + buildable"],
  ["build_ready",        "Build-ready (power + water)"],
  ["commercial",         "Commercial use"],
  ["agricultural",       "Agricultural"],
  ["under_50k",          "Under $50k"],
  ["under_100k",         "Under $100k"],
  ["price_drops",        "Repriced this cycle"],
  ["motivated_sellers",  "Motivated seller"],
];

const COHORT_OPTIONS = [
  ["pro_prefs",        "Pro + prefs (full picks, no paywall)"],
  ["free_prefs",       "Free + prefs (paywalled below pick #1)"],
  ["logged_no_prefs",  "Logged in, no prefs (fallback)"],
  ["anonymous",        "Anonymous email (welcome edition)"],
];

const PROPERTY_TYPES = ["land", "house", "condo"];

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const WIDGET_STYLES = `
.nl-widget {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 24px;
}
@media (min-width: 900px) {
  .nl-widget { grid-template-columns: minmax(0, 380px) minmax(0, 1fr); }
}
.nl-widget > * { min-width: 0; }
.nl-form {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.nl-form, .nl-form * { box-sizing: border-box; }
.nl-form .row { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.nl-form .row > label {
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-3);
  font-family: var(--font-mono);
}
.nl-form .row .hint { font-size: 12px; color: var(--ink-3); }
.nl-form input[type=text],
.nl-form input[type=number],
.nl-form select {
  font: inherit;
  padding: 8px 10px;
  border: 1px solid var(--line-2);
  border-radius: 6px;
  background: var(--paper);
  color: var(--ink);
  width: 100%;
  min-width: 0;
}
.nl-form input:focus, .nl-form select:focus {
  outline: 2px solid var(--accent);
  outline-offset: -1px;
}
.nl-form .row.inline { flex-direction: row; gap: 12px; align-items: center; }
.nl-form .row.inline > input { flex: 1; min-width: 0; }
.nl-form .checkbox-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 4px 12px;
}
@media (min-width: 480px) {
  .nl-form .checkbox-row { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
}
.nl-form .checkbox-row label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-2);
  cursor: pointer;
  min-width: 0;
  overflow-wrap: anywhere;
}
.nl-form .chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}
.nl-form .chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--paper-2);
  border: 1px solid var(--line-2);
  border-radius: 999px;
  padding: 2px 4px 2px 10px;
  font-size: 13px;
  color: var(--ink);
  max-width: 100%;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.nl-form .chip button {
  background: none;
  border: none;
  font: inherit;
  font-size: 14px;
  line-height: 1;
  color: var(--ink-3);
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 999px;
}
.nl-form .chip button:hover { color: var(--accent); }
.nl-form .price-range {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 8px;
}
.nl-form button.primary,
.nl-form button.secondary {
  appearance: none;
  font: inherit;
  font-weight: 600;
  border-radius: 8px;
  padding: 10px 16px;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease;
}
.nl-form button.primary {
  background: var(--accent);
  color: var(--paper);
  border: 1px solid var(--accent);
}
.nl-form button.primary:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
.nl-form button.primary[disabled],
.nl-form button.secondary[disabled] { opacity: 0.55; cursor: not-allowed; }
.nl-form button.secondary {
  background: var(--paper);
  color: var(--ink);
  border: 1px solid var(--line-2);
}
.nl-form button.secondary:hover { border-color: var(--accent); }
.nl-form .action-row { display: flex; gap: 8px; }

.nl-preview {
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  background: var(--paper);
  display: flex;
  flex-direction: column;
  min-height: 360px;
  min-width: 0;
  max-width: 100%;
}
.nl-preview, .nl-preview * { box-sizing: border-box; }
.nl-preview .preview-bar {
  padding: 10px 16px;
  background: var(--paper-2);
  border-bottom: 1px solid var(--line);
  font-size: 13px;
  color: var(--ink-2);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.nl-preview .preview-bar strong { color: var(--ink); }
.nl-preview .preview-empty {
  padding: 48px 24px;
  text-align: center;
  color: var(--ink-3);
  font-size: 14px;
}
.nl-preview iframe {
  flex: 1;
  width: 100%;
  border: none;
  min-height: 480px;
  background: var(--paper);
}
.nl-status {
  font-size: 13px;
  color: var(--ink-2);
  margin: 0;
  min-height: 18px;
}
.nl-status.error { color: var(--badge-drop); }
.nl-status.success { color: var(--accent-strong); }
`;

function ChipInput({ values, onChange, placeholder }) {
  const [draft, setDraft] = useState("");
  const commit = () => {
    const v = draft.trim();
    if (!v) return;
    if (values.includes(v)) { setDraft(""); return; }
    onChange([...values, v]);
    setDraft("");
  };
  return (
    <div>
      <div className="chip-list" style={{ marginBottom: 6 }}>
        {values.map((v) => (
          <span key={v} className="chip">
            {v}
            <button
              type="button"
              onClick={() => onChange(values.filter((x) => x !== v))}
              aria-label={`Remove ${v}`}
            >×</button>
          </span>
        ))}
      </div>
      <div className="row inline">
        <input
          type="text"
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
          }}
          onBlur={commit}
        />
      </div>
    </div>
  );
}

export function NewsletterWidget() {
  // ── Form state ───────────────────────────────────────────────────
  const [options, setOptions] = useState({
    departments: [], zones: [], property_types: [], total_listings: null, loading: true, error: null,
  });
  const [recipients, setRecipients] = useState([DEFAULT_RECIPIENT]);
  const [cohort, setCohort] = useState("pro_prefs");
  const [locale, setLocale] = useState("en");
  const [issueNumber, setIssueNumber] = useState(99);
  const [departments, setDepartments] = useState([]);
  const [zones, setZones] = useState([]);
  const [propertyTypes, setPropertyTypes] = useState([]);
  const [categories, setCategories] = useState([]);
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");

  // ── Output state ─────────────────────────────────────────────────
  const [previewHtml, setPreviewHtml] = useState(null);
  const [previewMeta, setPreviewMeta] = useState(null); // { picks_total, cohort, filter_trace }
  const [busy, setBusy] = useState(null); // "preview" | "send" | null
  const [status, setStatus] = useState({ kind: null, message: "" });

  // ── Load options on mount ────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    fetch("/api/admin/newsletter/options")
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then((data) => {
        if (cancelled) return;
        setOptions({
          departments: Array.isArray(data.departments) ? data.departments : [],
          zones: Array.isArray(data.zones) ? data.zones : [],
          property_types: Array.isArray(data.property_types) ? data.property_types : PROPERTY_TYPES,
          total_listings: typeof data.total_listings === "number" ? data.total_listings : null,
          loading: false,
          error: null,
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setOptions((s) => ({ ...s, loading: false, error: String(err && err.message || err) }));
      });
    return () => { cancelled = true; };
  }, []);

  // ── Filter payload ───────────────────────────────────────────────
  const filterSpec = useMemo(() => ({
    cohort,
    locale,
    issue_number: Number(issueNumber) || 1,
    preference: {
      departments,
      zones,
      property_types: propertyTypes,
      categories,
      min_price_usd: minPrice === "" ? null : Number(minPrice),
      max_price_usd: maxPrice === "" ? null : Number(maxPrice),
    },
  }), [cohort, locale, issueNumber, departments, zones, propertyTypes, categories, minPrice, maxPrice]);

  // ── Actions ──────────────────────────────────────────────────────
  const runPreview = async () => {
    setBusy("preview");
    setStatus({ kind: null, message: "" });
    try {
      const r = await fetch("/api/admin/newsletter/preview", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(filterSpec),
      });
      const ct = r.headers.get("content-type") || "";
      const isJson = ct.includes("application/json");
      const body = isJson ? await r.json() : { error: await r.text() };
      if (!r.ok) {
        setStatus({ kind: "error", message: body.error || `HTTP ${r.status}` });
        return;
      }
      setPreviewHtml(body.html || "");
      setPreviewMeta({
        picks_total: body.picks_total,
        cohort: body.cohort,
        filter_trace: body.filter_trace,
      });
      setStatus({
        kind: "success",
        message: `Preview ready — ${body.picks_total} picks selected from ${body.total_listings} listings.`,
      });
    } catch (err) {
      setStatus({ kind: "error", message: String(err && err.message || err) });
    } finally {
      setBusy(null);
    }
  };

  const runSend = async () => {
    const cleaned = recipients.map((s) => s.trim()).filter(Boolean);
    if (cleaned.length === 0) {
      setStatus({ kind: "error", message: "Add at least one recipient." });
      return;
    }
    if (cleaned.length > MAX_RECIPIENTS) {
      setStatus({ kind: "error", message: `Max ${MAX_RECIPIENTS} recipients per send.` });
      return;
    }
    for (const e of cleaned) {
      if (!EMAIL_RE.test(e)) {
        setStatus({ kind: "error", message: `Not a valid email: ${e}` });
        return;
      }
    }
    if (!confirm(`Send test newsletter to ${cleaned.length} recipient(s)?\n\n${cleaned.join("\n")}`)) {
      return;
    }
    setBusy("send");
    setStatus({ kind: null, message: "Sending…" });
    try {
      const r = await fetch("/api/admin/newsletter/send", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...filterSpec, recipients: cleaned }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setStatus({ kind: "error", message: body.error || `HTTP ${r.status}` });
        return;
      }
      setStatus({
        kind: "success",
        message: `Sent to ${body.sent}/${cleaned.length}. ${body.message_ids && body.message_ids.length ? `Message ID: ${body.message_ids[0]}` : ""}`,
      });
    } catch (err) {
      setStatus({ kind: "error", message: String(err && err.message || err) });
    } finally {
      setBusy(null);
    }
  };

  // ── Render ───────────────────────────────────────────────────────
  return (
    <>
      <style>{WIDGET_STYLES}</style>
      <div className="nl-widget">
        {/* ── Form ── */}
        <form
          className="nl-form"
          onSubmit={(e) => { e.preventDefault(); runPreview(); }}
        >
          <div className="row">
            <label htmlFor="nl-recipients">Send to (max {MAX_RECIPIENTS})</label>
            <ChipInput
              values={recipients}
              onChange={setRecipients}
              placeholder="add email, press Enter"
            />
            <span className="hint">
              Default is the admin owner. Press Enter or comma to add.
            </span>
          </div>

          <div className="row">
            <label htmlFor="nl-cohort">Cohort</label>
            <select id="nl-cohort" value={cohort} onChange={(e) => setCohort(e.target.value)}>
              {COHORT_OPTIONS.map(([k, label]) => (
                <option key={k} value={k}>{label}</option>
              ))}
            </select>
          </div>

          <div className="row">
            <label>Locale & issue</label>
            <div className="row inline">
              <select value={locale} onChange={(e) => setLocale(e.target.value)} style={{ flex: "0 0 90px" }}>
                <option value="en">English</option>
                <option value="es">Español</option>
              </select>
              <input
                type="number"
                value={issueNumber}
                min={1}
                onChange={(e) => setIssueNumber(e.target.value)}
                aria-label="Issue number"
              />
            </div>
            <span className="hint">Issue number stamps the email header; pick something high (e.g. 99) for tests.</span>
          </div>

          <div className="row">
            <label>Departments</label>
            <ChipInput values={departments} onChange={setDepartments} placeholder="e.g. La Libertad" />
            {options.departments.length > 0 && (
              <span className="hint">
                Available: {options.departments.slice(0, 6).join(", ")}{options.departments.length > 6 ? "…" : ""}
              </span>
            )}
          </div>

          <div className="row">
            <label>Zones</label>
            <ChipInput values={zones} onChange={setZones} placeholder="e.g. el-zonte" />
            {options.zones.length > 0 && (
              <span className="hint">
                {options.zones.length} zones available in current ranked.json
              </span>
            )}
          </div>

          <div className="row">
            <label>Property types</label>
            <div className="checkbox-row">
              {PROPERTY_TYPES.map((t) => (
                <label key={t}>
                  <input
                    type="checkbox"
                    checked={propertyTypes.includes(t)}
                    onChange={(e) => setPropertyTypes(
                      e.target.checked ? [...propertyTypes, t] : propertyTypes.filter((x) => x !== t)
                    )}
                  />
                  {t}
                </label>
              ))}
            </div>
          </div>

          <div className="row">
            <label>Categories</label>
            <div className="checkbox-row">
              {CATEGORY_OPTIONS.map(([k, label]) => (
                <label key={k}>
                  <input
                    type="checkbox"
                    checked={categories.includes(k)}
                    onChange={(e) => setCategories(
                      e.target.checked ? [...categories, k] : categories.filter((x) => x !== k)
                    )}
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>

          <div className="row">
            <label>Price range (USD)</label>
            <div className="price-range">
              <input
                type="number"
                value={minPrice}
                placeholder="min"
                onChange={(e) => setMinPrice(e.target.value)}
                aria-label="Minimum price"
                min={0}
              />
              <input
                type="number"
                value={maxPrice}
                placeholder="max"
                onChange={(e) => setMaxPrice(e.target.value)}
                aria-label="Maximum price"
                min={0}
              />
            </div>
          </div>

          <div className="action-row">
            <button type="submit" className="primary" disabled={busy != null}>
              {busy === "preview" ? "Rendering…" : "Preview"}
            </button>
            <button type="button" className="secondary" disabled={busy != null} onClick={runSend}>
              {busy === "send" ? "Sending…" : "Send test email"}
            </button>
          </div>

          <p
            className={`nl-status ${status.kind || ""}`}
            role={status.kind === "error" ? "alert" : undefined}
            aria-live="polite"
          >
            {status.message}
          </p>
        </form>

        {/* ── Preview pane ── */}
        <div className="nl-preview">
          <div className="preview-bar">
            <span>
              {previewMeta
                ? <><strong>{previewMeta.picks_total}</strong> picks · cohort <strong>{previewMeta.cohort}</strong></>
                : options.loading
                ? <>Loading available filter dimensions…</>
                : options.error
                ? <>Could not load options: {options.error}</>
                : <>{options.total_listings ?? "—"} listings in pool</>}
            </span>
            {previewMeta?.filter_trace && (
              <span title={JSON.stringify(previewMeta.filter_trace, null, 2)}>
                filter applied
              </span>
            )}
          </div>
          {previewHtml ? (
            <iframe
              title="Newsletter preview"
              srcDoc={previewHtml}
              sandbox="allow-same-origin"
            />
          ) : (
            <div className="preview-empty">
              Fill in the filter and click Preview to render. The send button uses the same spec.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
