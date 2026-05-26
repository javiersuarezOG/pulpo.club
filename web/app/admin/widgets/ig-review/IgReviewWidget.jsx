// IgReviewWidget — visual review surface for the IG batch queue.
//
// Reads /api/admin/ig-queue (which forwards web/data/ig_queue.json built
// by automation/ig_queue_builder.py).  Renders all 14 items in
// chronological order: each item shows poster thumbnail, shelf, caption,
// status, and a local-only approval toggle.
//
// PR-3b scope (this file) is READ + LOCAL-ONLY MUTATION:
//   - GET endpoint provides the canonical queue
//   - Approve / skip decisions live in the operator's localStorage so
//     they persist across refresh and across the multi-day review window
//   - "Submit batch for publish" button is wired but disabled — clicking
//     it shows a hint pointing at PR-4 where the workflow_dispatch flow
//     lands and the decisions get committed back to queue.json + the
//     publisher kicks off
//
// Why localStorage and not the API: the queue file is committed to the
// repo via the nightly bot.  Mutating it from a serverless function
// would require a GitHub Contents API utility we don't have yet.  PR-4
// adds workflow_dispatch (same pattern the newsletter widget uses) so
// the approval ceremony stays on rails when we're ready to publish.
//
// i18n: every user-visible string flows through t() per CLAUDE.md.  The
// existing NewsletterWidget inlines English — that's a pre-existing
// violation we're not propagating into the new widgets.
//
// Mobile-first: 320px viewport must render usable.  The card layout
// stacks below 640px and the poster thumb shrinks to a constant 88px
// (Instagram-like density rather than full-bleed).

import React, { useEffect, useMemo, useState } from "react";
import { t } from "../../../i18n.jsx";

const STORAGE_KEY = "pulpo-ig-review-decisions/drop_01";
const QUEUE_ENDPOINT = "/api/admin/ig-queue";

// Per-item decision the operator records locally.  null = no decision yet
// (the queue's own `status` from the builder still applies).
const DECISION_NONE   = null;
const DECISION_APPROVE = "approve";
const DECISION_SKIP   = "skip";

function _readDecisions() {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return (parsed && typeof parsed === "object") ? parsed : {};
  } catch {
    return {};
  }
}

function _writeDecisions(decisions) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions));
  } catch {
    /* localStorage full / blocked — silently skip; widget still works in-memory */
  }
}

// Status badge style by queue-item status + operator decision.
function _statusBadge(item, decision) {
  if (decision === DECISION_APPROVE)
    return { kind: "approve", label: t("admin.ig_review.status.approved") };
  if (decision === DECISION_SKIP)
    return { kind: "skip",    label: t("admin.ig_review.status.skipped") };
  if (item.status === "needs_human")
    return { kind: "alert",   label: t("admin.ig_review.status.needs_human") };
  if (item.status === "posted")
    return { kind: "posted",  label: t("admin.ig_review.status.posted") };
  return { kind: "pending",   label: t("admin.ig_review.status.pending") };
}

// Map the queue item's local PNG path to a public URL the browser can
// load.  The renderer writes to `web/data/ig_assets/...` which Vercel
// serves at `/data/ig_assets/...`.
function _posterPublicUrl(posterPath) {
  if (!posterPath) return null;
  // Strip the leading `web/` so the path becomes `/data/ig_assets/...`.
  const trimmed = posterPath.replace(/^web\//, "");
  return `/${trimmed}`;
}

function _scheduledLabel(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("es-SV", {
      weekday: "short",
      day:     "numeric",
      month:   "short",
      hour:    "2-digit",
      minute:  "2-digit",
    });
  } catch {
    return iso;
  }
}

const WIDGET_STYLES = `
.ig-review-widget {
  max-width: 1100px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  color: var(--ink);
}
.ig-review-empty,
.ig-review-error,
.ig-review-loading {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ig-review-empty h3,
.ig-review-error h3 {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 400;
  font-size: 22px;
  margin: 0;
  letter-spacing: -.01em;
}
.ig-review-empty p,
.ig-review-error p {
  font-size: 14px;
  color: var(--ink-2);
  margin: 0;
  line-height: 1.55;
}
.ig-review-empty code,
.ig-review-error code {
  font-family: var(--font-mono);
  font-size: 13px;
  background: var(--paper-2);
  padding: 2px 8px;
  border-radius: 4px;
  color: var(--ink);
}
.ig-review-summary {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px 20px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}
.ig-review-summary .stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.ig-review-summary .stat {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: .12em;
  text-transform: uppercase;
  font-weight: 700;
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 12px;
  color: var(--ink-2);
}
.ig-review-summary .stat b {
  color: var(--ink);
  font-weight: 800;
}
.ig-review-summary .stat.alert b { color: var(--accent-2); }
.ig-review-summary .stat.approve b { color: var(--accent); }
.ig-review-summary .submit {
  font-family: var(--font-sans);
  font-weight: 700;
  font-size: 13px;
  background: var(--ink);
  color: var(--paper);
  border: none;
  border-radius: 10px;
  padding: 10px 18px;
  cursor: not-allowed;
  opacity: .55;
}
.ig-review-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ig-review-item {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 16px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 16px;
}
.ig-review-item.alert  { border-left: 4px solid var(--accent-2); }
.ig-review-item.approve { border-left: 4px solid var(--accent); }
.ig-review-item.skip   { border-left: 4px solid var(--ink-3); opacity: .65; }
.ig-review-item .poster-thumb {
  width: 88px;
  aspect-ratio: 4 / 5;
  border-radius: 8px;
  overflow: hidden;
  background: var(--paper-2);
  border: 1px solid var(--line);
  position: relative;
}
.ig-review-item .poster-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.ig-review-item .poster-thumb .missing {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .12em;
  color: var(--ink-3);
  text-align: center;
  padding: 4px;
}
.ig-review-item .body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.ig-review-item .head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  align-items: baseline;
}
.ig-review-item .day {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: .12em;
  font-weight: 800;
  color: var(--accent);
}
.ig-review-item .shelf {
  font-family: var(--font-display);
  font-style: italic;
  font-size: 18px;
  font-weight: 400;
  color: var(--ink);
  letter-spacing: -.01em;
}
.ig-review-item .meta {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-3);
  letter-spacing: .04em;
}
.ig-review-item .meta b { color: var(--ink-2); font-weight: 700; }
.ig-review-item .caption {
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink-2);
  background: var(--paper-2);
  border-radius: 8px;
  padding: 10px 12px;
  white-space: pre-wrap;
  max-height: 6.5em;
  overflow: hidden;
  position: relative;
}
.ig-review-item .caption.expanded {
  max-height: none;
}
.ig-review-item .caption-toggle {
  background: none;
  border: none;
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: .08em;
  cursor: pointer;
  padding: 4px 0 0;
  text-transform: uppercase;
  font-weight: 700;
  align-self: flex-start;
}
.ig-review-item .violations {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent-2);
  background: oklch(0.95 0.04 25);
  border-radius: 6px;
  padding: 6px 10px;
  letter-spacing: .04em;
}
.ig-review-item .actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.ig-review-item .actions button {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: .08em;
  font-weight: 700;
  text-transform: uppercase;
  background: var(--paper-2);
  color: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px 12px;
  cursor: pointer;
  min-height: 32px;
}
.ig-review-item .actions button:hover { background: var(--paper-3); }
.ig-review-item .actions button.active.approve {
  background: var(--accent);
  color: var(--paper);
  border-color: var(--accent);
}
.ig-review-item .actions button.active.skip {
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
}
.ig-review-item .badge {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .14em;
  text-transform: uppercase;
  font-weight: 800;
  padding: 4px 8px;
  border-radius: 5px;
  background: var(--paper-2);
  color: var(--ink-2);
  border: 1px solid var(--line);
  align-self: flex-start;
}
.ig-review-item .badge.alert    { background: oklch(0.95 0.04 25); color: var(--accent-2); border-color: oklch(0.85 0.10 25); }
.ig-review-item .badge.approve  { background: oklch(0.94 0.06 145); color: var(--accent); border-color: oklch(0.85 0.10 145); }
.ig-review-item .badge.posted   { background: oklch(0.93 0.04 165); color: var(--accent-strong); border-color: oklch(0.85 0.10 165); }

@media (max-width: 640px) {
  .ig-review-item {
    grid-template-columns: 72px 1fr;
    gap: 12px;
    padding: 12px;
  }
  .ig-review-item .poster-thumb { width: 72px; }
  .ig-review-item .shelf { font-size: 16px; }
  .ig-review-summary .submit { width: 100%; text-align: center; }
}
@media (max-width: 360px) {
  .ig-review-item { grid-template-columns: 1fr; }
  .ig-review-item .poster-thumb { width: 100%; max-width: 200px; }
}
`;

function _StatsBar({ items, decisions }) {
  const counts = useMemo(() => {
    let approve = 0, skip = 0, alert = 0, posted = 0, pending = 0;
    for (const it of items) {
      const d = decisions[String(it.day)];
      if (d === DECISION_APPROVE) { approve++; continue; }
      if (d === DECISION_SKIP)    { skip++;   continue; }
      if (it.status === "needs_human") { alert++; continue; }
      if (it.status === "posted")      { posted++; continue; }
      pending++;
    }
    return { approve, skip, alert, posted, pending, total: items.length };
  }, [items, decisions]);
  return (
    <div className="ig-review-summary">
      <div className="stats">
        <span className="stat">
          {t("admin.ig_review.stat.total")}: <b>{counts.total}</b>
        </span>
        <span className={`stat approve`}>
          {t("admin.ig_review.stat.approved")}: <b>{counts.approve}</b>
        </span>
        <span className="stat">
          {t("admin.ig_review.stat.skipped")}: <b>{counts.skip}</b>
        </span>
        <span className={`stat alert`}>
          {t("admin.ig_review.stat.needs_human")}: <b>{counts.alert}</b>
        </span>
        <span className="stat">
          {t("admin.ig_review.stat.pending")}: <b>{counts.pending}</b>
        </span>
        {counts.posted > 0 && (
          <span className="stat">
            {t("admin.ig_review.stat.posted")}: <b>{counts.posted}</b>
          </span>
        )}
      </div>
      <button
        type="button"
        className="submit"
        disabled
        title={t("admin.ig_review.submit_disabled_hint")}
        aria-label={t("admin.ig_review.submit_disabled_hint")}
      >
        {t("admin.ig_review.submit_button")}
      </button>
    </div>
  );
}

function _Item({ item, decision, onDecide }) {
  const [expanded, setExpanded] = useState(false);
  const badge = _statusBadge(item, decision);
  const posterUrl = _posterPublicUrl(item.poster_path);
  const captionText = (item.caption || "").trim();
  const captionLong = captionText.length > 180;
  const violations = Array.isArray(item.lint_violations) ? item.lint_violations : [];
  const itemClass = decision === DECISION_APPROVE ? "approve"
                 : decision === DECISION_SKIP    ? "skip"
                 : item.status === "needs_human" ? "alert"
                 : "";

  return (
    <article
      className={`ig-review-item ${itemClass}`}
      aria-label={t("admin.ig_review.item_aria", {
        day: String(item.day),
        shelf: item.shelf || "",
      })}
    >
      <div className="poster-thumb">
        {posterUrl ? (
          <img
            src={posterUrl}
            alt={t("admin.ig_review.poster_alt", { day: String(item.day) })}
            loading="lazy"
          />
        ) : (
          <div className="missing">{t("admin.ig_review.no_poster")}</div>
        )}
      </div>
      <div className="body">
        <div className="head">
          <span className="day">D{String(item.day).padStart(2, "0")}</span>
          <span className="shelf">{item.shelf || "—"}</span>
          <span className={`badge ${badge.kind}`}>{badge.label}</span>
        </div>
        <div className="meta">
          <b>{(item.poster_type || "—").toUpperCase()}</b>
          {item.palette ? ` · ${item.palette}` : ""}
          {item.primary_listing_id
            ? ` · ${item.primary_listing_id}`
            : ` · ${(item.listing_ids || []).length} ${t("admin.ig_review.listings")}`}
          {item.scheduled_for ? ` · ${_scheduledLabel(item.scheduled_for)}` : ""}
        </div>
        {captionText && (
          <div className={`caption${expanded ? " expanded" : ""}`}>
            {captionText}
          </div>
        )}
        {captionLong && (
          <button
            type="button"
            className="caption-toggle"
            onClick={() => setExpanded((x) => !x)}
          >
            {expanded
              ? t("admin.ig_review.caption_collapse")
              : t("admin.ig_review.caption_expand")}
          </button>
        )}
        {violations.length > 0 && (
          <div
            className="violations"
            role="alert"
            aria-label={t("admin.ig_review.lint_alert")}
          >
            {t("admin.ig_review.lint_prefix")}:{" "}
            {violations.map((v) => v.code).join(" · ")}
          </div>
        )}
        <div className="actions">
          <button
            type="button"
            className={`approve${decision === DECISION_APPROVE ? " active" : ""}`}
            onClick={() => onDecide(item.day, DECISION_APPROVE)}
            aria-pressed={decision === DECISION_APPROVE}
          >
            {t("admin.ig_review.action.approve")}
          </button>
          <button
            type="button"
            className={`skip${decision === DECISION_SKIP ? " active" : ""}`}
            onClick={() => onDecide(item.day, DECISION_SKIP)}
            aria-pressed={decision === DECISION_SKIP}
          >
            {t("admin.ig_review.action.skip")}
          </button>
          {decision !== DECISION_NONE && (
            <button
              type="button"
              onClick={() => onDecide(item.day, DECISION_NONE)}
              aria-label={t("admin.ig_review.action.clear")}
            >
              {t("admin.ig_review.action.clear")}
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

export function IgReviewWidget() {
  const [state, setState] = useState({ kind: "loading", data: null, error: null });
  const [decisions, setDecisions] = useState(() => _readDecisions());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(QUEUE_ENDPOINT, { headers: { "Accept": "application/json" } });
        const body = await r.json().catch(() => ({}));
        if (cancelled) return;
        if (!r.ok) {
          setState({ kind: "error", data: null, error: body.error || `HTTP ${r.status}` });
          return;
        }
        setState({ kind: "loaded", data: body, error: null });
      } catch (err) {
        if (cancelled) return;
        setState({ kind: "error", data: null, error: (err && err.message) || "fetch_failed" });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  function setDecision(day, value) {
    setDecisions((prev) => {
      const next = { ...prev };
      if (value === DECISION_NONE) delete next[String(day)];
      else next[String(day)] = value;
      _writeDecisions(next);
      return next;
    });
  }

  return (
    <div className="ig-review-widget" aria-label={t("admin.ig_review.aria_root")}>
      <style>{WIDGET_STYLES}</style>

      {state.kind === "loading" && (
        <div className="ig-review-loading" role="status">
          {t("admin.ig_review.loading")}
        </div>
      )}

      {state.kind === "error" && (
        <div className="ig-review-error" role="alert">
          <h3>{t("admin.ig_review.error_heading")}</h3>
          <p>{t("admin.ig_review.error_body", { detail: state.error || "" })}</p>
        </div>
      )}

      {state.kind === "loaded" && state.data && !state.data.queue && (
        <div className="ig-review-empty">
          <h3>{t("admin.ig_review.empty_heading")}</h3>
          <p>{state.data.hint || t("admin.ig_review.empty_body")}</p>
          <p>
            <code>python3 -m automation.ig_queue_builder</code>
          </p>
        </div>
      )}

      {state.kind === "loaded" && state.data && state.data.queue && (
        <>
          <_StatsBar items={state.data.queue.items || []} decisions={decisions} />
          <ol className="ig-review-list" aria-label={t("admin.ig_review.list_aria")}>
            {(state.data.queue.items || []).map((it) => (
              <li key={`d${it.day}-${it.shelf}`} style={{ listStyle: "none" }}>
                <_Item
                  item={it}
                  decision={decisions[String(it.day)] || DECISION_NONE}
                  onDecide={setDecision}
                />
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

// /admin grid preview tile — narrow summary, no actions.
export function IgReviewPreview() {
  const [state, setState] = useState({ kind: "loading", queue: null });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(QUEUE_ENDPOINT);
        const body = await r.json().catch(() => ({}));
        if (cancelled) return;
        setState({ kind: r.ok ? "loaded" : "error", queue: body && body.queue });
      } catch {
        if (cancelled) return;
        setState({ kind: "error", queue: null });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const stats = useMemo(() => {
    if (!state.queue || !Array.isArray(state.queue.items)) return null;
    let approve = 0, alert = 0, posted = 0;
    const decisions = _readDecisions();
    for (const it of state.queue.items) {
      if (decisions[String(it.day)] === DECISION_APPROVE) approve++;
      else if (it.status === "needs_human") alert++;
      else if (it.status === "posted") posted++;
    }
    return { total: state.queue.items.length, approve, alert, posted };
  }, [state.queue]);

  if (state.kind === "loading") {
    return (
      <div style={{ fontSize: 12, color: "var(--ink-3)", fontFamily: "var(--font-mono)" }}>
        {t("admin.ig_review.preview_loading")}
      </div>
    );
  }
  if (!stats) {
    return (
      <div style={{ fontSize: 12, color: "var(--ink-3)", fontFamily: "var(--font-mono)" }}>
        {t("admin.ig_review.preview_empty")}
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: ".10em", color: "var(--ink-2)", fontWeight: 700, textTransform: "uppercase" }}>
        {t("admin.ig_review.preview_title", { total: String(stats.total) })}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 11, color: "var(--ink-3)" }}>
        <span style={{ color: "var(--accent)" }}>
          ✓ {stats.approve} {t("admin.ig_review.stat.approved").toLowerCase()}
        </span>
        {stats.alert > 0 && (
          <span style={{ color: "var(--accent-2)" }}>
            ⚠ {stats.alert} {t("admin.ig_review.stat.needs_human").toLowerCase()}
          </span>
        )}
        {stats.posted > 0 && (
          <span style={{ color: "var(--accent-strong)" }}>
            ⇪ {stats.posted} {t("admin.ig_review.stat.posted").toLowerCase()}
          </span>
        )}
      </div>
    </div>
  );
}
