// IgReviewWidget — full Instagram-style preview surface for the IG batch.
//
// For each queue item the widget renders an IG-shaped post card showing
// EXACTLY what the carousel will look like once published:
//   - Header: pulpo.club ✓ + day pill
//   - Slide 1 — the rendered poster PNG (1080×1350)
//   - Slides 2..N — the carousel photos (Vercel-served /photos/*.jpg)
//   - Carousel dots, IG action icons (♡ 💬 ↗ 🔖)
//   - Caption with `**bold**` rendered, newlines preserved
//   - Scheduled-for label
//   - Lint violations (if any) + Approve / Skip / Clear actions
//
// Operator decisions still live in localStorage for PR-3b → PR-5.  The
// workflow_dispatch persistence (so "Submit batch" actually writes back
// to ig_queue.json) lands in a follow-up.  Until then, to ship an item
// the operator hand-edits web/data/ig_queue.json and sets approved=true.
//
// IgReviewPreview — narrow live-data tile rendered on the /admin grid.
// Reads /api/admin/ig-queue and surfaces health: items_approved /
// _pending / _needs_human, last_posted_at, next_due, and blockers
// (missing secrets, IG_PAUSED, nothing approved, overdue items).
// Colour-coded so a single glance tells the operator whether the
// publishing pipeline is healthy or stuck.
//
// Mobile-first: the IG post frame caps at 380px and the layout stacks
// to a single column below 720px so 320×568 still renders usable.

import React, { useEffect, useMemo, useRef, useState } from "react";
import { t } from "../../../i18n.jsx";

const STORAGE_KEY = "pulpo-ig-review-decisions/drop_01";
const QUEUE_ENDPOINT = "/api/admin/ig-queue";

// Operator decision codes.  null = no local decision; the queue's own
// approved/posted flags still apply.
const DECISION_NONE     = null;
const DECISION_APPROVE  = "approve";
const DECISION_SKIP     = "skip";

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
    /* localStorage full / blocked — silently skip */
  }
}

// `web/data/ig_assets/...` → `/data/ig_assets/...` ; same for `/photos/`.
function _publicUrl(localPath) {
  if (!localPath) return null;
  return "/" + localPath.replace(/^web\//, "");
}

// Renders `**bold**` runs as <strong> and preserves newlines as <br/>.
// Defensive: never reflects raw HTML from the caption (only matched
// **text** groups are wrapped) so a leaked < in a caption can't break
// out into markup.
function _renderCaption(text) {
  if (!text) return null;
  const safe = String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  // Walk text, match **...** runs, emit React fragments.
  const out = [];
  const re = /\*\*([^*]+)\*\*/g;
  let lastIdx = 0;
  let m;
  let key = 0;
  while ((m = re.exec(safe)) !== null) {
    if (m.index > lastIdx) {
      out.push(<React.Fragment key={key++}>{_withBreaks(safe.slice(lastIdx, m.index), key)}</React.Fragment>);
    }
    out.push(<strong key={key++}>{_withBreaks(m[1], key)}</strong>);
    lastIdx = m.index + m[0].length;
  }
  if (lastIdx < safe.length) {
    out.push(<React.Fragment key={key++}>{_withBreaks(safe.slice(lastIdx), key)}</React.Fragment>);
  }
  return out;
}

function _withBreaks(s, baseKey) {
  const lines = s.split(/\n/);
  const out = [];
  lines.forEach((line, i) => {
    if (i > 0) out.push(<br key={`${baseKey}-br-${i}`} />);
    if (line) out.push(line);
  });
  return out;
}

function _scheduledLabel(iso, locale = "es-SV") {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(locale, {
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

function _relativeFromNow(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return null;
  const deltaMs = d.getTime() - Date.now();
  const absMs = Math.abs(deltaMs);
  const sign = deltaMs < 0 ? "ago" : "in";
  const minutes = Math.round(absMs / 60000);
  if (minutes < 60) return `${sign === "ago" ? "" : "in "}${minutes}m${sign === "ago" ? " ago" : ""}`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${sign === "ago" ? "" : "in "}${hours}h${sign === "ago" ? " ago" : ""}`;
  const days = Math.round(hours / 24);
  return `${sign === "ago" ? "" : "in "}${days}d${sign === "ago" ? " ago" : ""}`;
}

// Status label + colour key.
function _statusBadge(item, decision) {
  if (decision === DECISION_APPROVE)
    return { kind: "approve", label: t("admin.ig_review.status.approved") };
  if (decision === DECISION_SKIP)
    return { kind: "skip", label: t("admin.ig_review.status.skipped") };
  if (item.posted === true)
    return { kind: "posted", label: t("admin.ig_review.status.posted") };
  if (item.status === "needs_human")
    return { kind: "alert", label: t("admin.ig_review.status.needs_human") };
  return { kind: "pending", label: t("admin.ig_review.status.pending") };
}


// ── styles ───────────────────────────────────────────────────────────

const WIDGET_STYLES = `
.ig-review-widget {
  display: flex;
  flex-direction: column;
  gap: 18px;
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

/* ============ HEALTH BANNER ============ */
.ig-health-bar {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px 20px;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 14px 18px;
  align-items: center;
}
.ig-health-bar.alert { border-left: 4px solid var(--accent-2); }
.ig-health-bar.ok    { border-left: 4px solid var(--accent); }
.ig-health-bar .stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
}
.ig-health-bar .chip {
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
.ig-health-bar .chip b { color: var(--ink); font-weight: 800; }
.ig-health-bar .chip.green  b { color: var(--accent); }
.ig-health-bar .chip.alert  b { color: var(--accent-2); }
.ig-health-bar .chip.muted  b { color: var(--ink-3); }
.ig-health-bar .submit {
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
  white-space: nowrap;
}
.ig-health-bar .meta {
  grid-column: 1 / -1;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-3);
  letter-spacing: .04em;
  border-top: 1px dashed var(--line);
  padding-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
}
.ig-health-bar .meta b { color: var(--ink-2); font-weight: 700; }
.ig-health-bar .blockers {
  grid-column: 1 / -1;
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ig-health-bar .blocker {
  font-size: 13px;
  color: var(--accent-2);
  background: oklch(0.95 0.04 25);
  border: 1px solid oklch(0.85 0.10 25);
  border-radius: 8px;
  padding: 8px 12px;
  line-height: 1.45;
  font-family: var(--font-sans);
}

/* ============ IG POST CARD ============ */
.ig-review-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.ig-review-item {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 24px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px;
  align-items: start;
}
.ig-review-item.alert    { border-left: 4px solid var(--accent-2); }
.ig-review-item.approve  { border-left: 4px solid var(--accent); }
.ig-review-item.skip     { border-left: 4px solid var(--ink-3); opacity: .65; }
.ig-review-item.posted   { border-left: 4px solid var(--accent-strong); }

@media (max-width: 720px) {
  .ig-review-item {
    grid-template-columns: 1fr;
    gap: 14px;
    padding: 14px;
  }
}

/* IG card frame */
.ig-card {
  width: 100%;
  max-width: 380px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 1px 2px oklch(0 0 0 / 0.04), 0 4px 12px oklch(0 0 0 / 0.04);
}
.ig-card .ig-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}
.ig-card .avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--ink);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.ig-card .handle {
  font-size: 14px;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.2;
}
.ig-card .handle .verif { color: #3897f0; font-size: 12px; margin-left: 2px; }
.ig-card .head-meta {
  display: flex;
  flex-direction: column;
}
.ig-card .head-meta .sub {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .12em;
  color: var(--ink-3);
  text-transform: uppercase;
  margin-top: 2px;
}
.ig-card .day-pill {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .14em;
  font-weight: 800;
  text-transform: uppercase;
  background: var(--paper-2);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 4px 9px;
  color: var(--ink-2);
}

/* Carousel — horizontal scroll-snap, dots row underneath */
.ig-card .carousel {
  position: relative;
  background: var(--ink-deep);
  scroll-snap-type: x mandatory;
  display: flex;
  overflow-x: auto;
  scroll-behavior: smooth;
}
.ig-card .carousel::-webkit-scrollbar { display: none; }
.ig-card .carousel { -ms-overflow-style: none; scrollbar-width: none; }
.ig-card .slide {
  flex: 0 0 100%;
  scroll-snap-align: start;
  aspect-ratio: 4 / 5;
  position: relative;
  display: block;
  background: var(--ink-deep);
  width: 100%;
}
.ig-card .slide img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.ig-card .slide .missing {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: .12em;
  color: var(--ink-3);
  background: var(--paper-2);
}
.ig-card .slide-count {
  position: absolute;
  top: 12px;
  right: 12px;
  background: oklch(0 0 0 / .55);
  color: var(--paper);
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: .08em;
  font-weight: 700;
  padding: 3px 9px;
  pointer-events: none;
}
.ig-card .dots {
  display: flex;
  justify-content: center;
  gap: 4px;
  padding: 8px 0;
  background: var(--paper);
  border-bottom: 1px solid var(--line);
}
.ig-card .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--line);
  transition: background 120ms;
}
.ig-card .dot.active { background: var(--ink); }
.ig-card .actions {
  display: flex;
  gap: 14px;
  padding: 8px 14px 2px;
  font-size: 22px;
  color: var(--ink);
}
.ig-card .actions .save { margin-left: auto; }
.ig-card .caption {
  padding: 4px 14px 14px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink);
  white-space: normal;
  word-wrap: break-word;
}
.ig-card .caption strong { font-weight: 800; }

/* Side panel: meta + status + actions */
.ig-side {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}
.ig-side .badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.ig-side .badge {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: .14em;
  text-transform: uppercase;
  font-weight: 800;
  padding: 4px 9px;
  border-radius: 5px;
  background: var(--paper-2);
  color: var(--ink-2);
  border: 1px solid var(--line);
}
.ig-side .badge.alert    { background: oklch(0.95 0.04 25); color: var(--accent-2); border-color: oklch(0.85 0.10 25); }
.ig-side .badge.approve  { background: oklch(0.94 0.06 145); color: var(--accent); border-color: oklch(0.85 0.10 145); }
.ig-side .badge.posted   { background: oklch(0.93 0.04 165); color: var(--accent-strong); border-color: oklch(0.85 0.10 165); }

.ig-side .row {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-3);
  letter-spacing: .04em;
}
.ig-side .row b { color: var(--ink-2); font-weight: 700; min-width: 90px; }
.ig-side .row a { color: var(--accent); text-decoration: none; }
.ig-side .row a:hover { text-decoration: underline; }

.ig-side .violations {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent-2);
  background: oklch(0.95 0.04 25);
  border: 1px solid oklch(0.85 0.10 25);
  border-radius: 6px;
  padding: 8px 10px;
  letter-spacing: .04em;
}

.ig-side .actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.ig-side .actions button {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: .08em;
  font-weight: 700;
  text-transform: uppercase;
  background: var(--paper-2);
  color: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 14px;
  cursor: pointer;
  min-height: 36px;
}
.ig-side .actions button:hover { background: var(--paper-3); }
.ig-side .actions button.active.approve {
  background: var(--accent);
  color: var(--paper);
  border-color: var(--accent);
}
.ig-side .actions button.active.skip {
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
}

/* ============ PREVIEW TILE (for /admin grid) ============ */
.ig-preview-tile {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ig-preview-tile .total {
  font-family: var(--font-display);
  font-style: italic;
  font-size: 28px;
  line-height: 1;
  color: var(--ink);
  font-weight: 400;
  letter-spacing: -.01em;
}
.ig-preview-tile .total b { color: var(--accent); font-weight: 400; }
.ig-preview-tile .row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: .04em;
  color: var(--ink-3);
}
.ig-preview-tile .row .good { color: var(--accent); }
.ig-preview-tile .row .alert { color: var(--accent-2); }
.ig-preview-tile .row b { color: var(--ink); font-weight: 700; }
.ig-preview-tile .blocker {
  font-size: 11px;
  color: var(--accent-2);
  background: oklch(0.95 0.04 25);
  border-radius: 5px;
  padding: 4px 8px;
  line-height: 1.4;
}
`;


// ── per-item: full IG-style preview ─────────────────────────────────

function _Slides({ posterUrl, photoUrls, dayLabel }) {
  const [active, setActive] = useState(0);
  const ref = useRef(null);
  const slides = [];
  if (posterUrl) slides.push({ key: "poster", url: posterUrl, kind: "poster" });
  for (const u of photoUrls) slides.push({ key: u, url: u, kind: "photo" });

  // Track active slide via scroll position so the dots row stays in sync
  // with the user's swipe.  Using IntersectionObserver would be nicer but
  // scrollLeft / width is simpler and fast enough for the admin surface.
  useEffect(() => {
    const el = ref.current;
    if (!el || slides.length <= 1) return undefined;
    let raf = 0;
    const onScroll = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const w = el.clientWidth || 1;
        setActive(Math.round(el.scrollLeft / w));
      });
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [slides.length]);

  if (slides.length === 0) {
    return (
      <div className="carousel">
        <div className="slide"><div className="missing">{t("admin.ig_review.no_poster")}</div></div>
      </div>
    );
  }

  return (
    <>
      <div className="carousel" ref={ref} aria-label={t("admin.ig_review.carousel_aria", { day: dayLabel })}>
        {slides.map((s, i) => (
          <div className="slide" key={s.key}>
            <img src={s.url} alt={t("admin.ig_review.slide_alt", { n: String(i + 1) })} loading="lazy" />
            {slides.length > 1 && (
              <span className="slide-count">{i + 1}/{slides.length}</span>
            )}
          </div>
        ))}
      </div>
      {slides.length > 1 && (
        <div className="dots" role="presentation">
          {slides.map((_, i) => (
            <span key={i} className={`dot${i === active ? " active" : ""}`} />
          ))}
        </div>
      )}
    </>
  );
}

const _PULPO_AVATAR_SVG = (
  <svg viewBox="0 0 100 100" width="20" height="20" xmlns="http://www.w3.org/2000/svg">
    <ellipse cx="50" cy="34" rx="22" ry="24" fill="#fff" />
    <circle cx="42" cy="32" r="2.5" fill="white" />
    <circle cx="58" cy="32" r="2.5" fill="white" />
    <path d="M 30 54 Q 18 68 22 92" stroke="#fff" strokeWidth="4.5" fill="none" strokeLinecap="round" />
    <path d="M 39 58 Q 30 78 36 94" stroke="#fff" strokeWidth="4.5" fill="none" strokeLinecap="round" />
    <path d="M 47 60 Q 46 80 50 95" stroke="#fff" strokeWidth="4.5" fill="none" strokeLinecap="round" />
    <path d="M 55 60 Q 56 80 62 94" stroke="#fff" strokeWidth="4.5" fill="none" strokeLinecap="round" />
    <path d="M 62 58 Q 70 78 76 92" stroke="#fff" strokeWidth="4.5" fill="none" strokeLinecap="round" />
    <path d="M 70 54 Q 82 68 80 88" stroke="#fff" strokeWidth="4.5" fill="none" strokeLinecap="round" />
  </svg>
);

function _Item({ item, decision, onDecide }) {
  const badge = _statusBadge(item, decision);
  const posterUrl = _publicUrl(item.poster_path);
  const photoUrls = (item.carousel_photo_paths || []).map(_publicUrl).filter(Boolean);
  const violations = Array.isArray(item.lint_violations) ? item.lint_violations : [];
  const itemClass = decision === DECISION_APPROVE ? "approve"
                 : decision === DECISION_SKIP    ? "skip"
                 : item.posted === true          ? "posted"
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
      <div className="ig-card">
        <div className="ig-head">
          <div className="avatar">{_PULPO_AVATAR_SVG}</div>
          <div className="head-meta">
            <span className="handle">pulpo.club <span className="verif">✓</span></span>
            <span className="sub">{(item.poster_type || "—").toUpperCase()} · {item.palette || ""}</span>
          </div>
          <span className="day-pill">D{String(item.day).padStart(2, "0")}</span>
        </div>
        <_Slides posterUrl={posterUrl} photoUrls={photoUrls} dayLabel={String(item.day)} />
        <div className="actions" aria-hidden="true">
          <span>♡</span>
          <span>💬</span>
          <span>↗</span>
          <span className="save">🔖</span>
        </div>
        <div className="caption">{_renderCaption(item.caption)}</div>
      </div>

      <div className="ig-side">
        <div className="badges">
          <span className={`badge ${badge.kind}`}>{badge.label}</span>
          <span className="badge">{item.shelf || "—"}</span>
        </div>
        <div className="row">
          <b>{t("admin.ig_review.scheduled")}</b>
          <span>{_scheduledLabel(item.scheduled_for)}{
            _relativeFromNow(item.scheduled_for)
              ? ` · ${_relativeFromNow(item.scheduled_for)}` : ""
          }</span>
        </div>
        <div className="row">
          <b>{t("admin.ig_review.primary")}</b>
          <span>{item.primary_listing_id || `${(item.listing_ids || []).length} ${t("admin.ig_review.listings")}`}</span>
        </div>
        {item.posted && item.posted_at && (
          <div className="row">
            <b>{t("admin.ig_review.posted_at")}</b>
            <span>{_scheduledLabel(item.posted_at)}</span>
          </div>
        )}
        {item.posted_media_id && (
          <div className="row">
            <b>{t("admin.ig_review.media_id")}</b>
            <span>{item.posted_media_id}</span>
          </div>
        )}
        {violations.length > 0 && (
          <div className="violations" role="alert" aria-label={t("admin.ig_review.lint_alert")}>
            {t("admin.ig_review.lint_prefix")}: {violations.map((v) => v.code).join(" · ")}
          </div>
        )}
        {item.posted !== true && (
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
        )}
      </div>
    </article>
  );
}


// ── health banner ────────────────────────────────────────────────────

function _HealthBanner({ health, items, decisions }) {
  const counts = useMemo(() => {
    let approve = 0, skip = 0, alert = 0, posted = 0, pending = 0;
    for (const it of items) {
      const d = decisions[String(it.day)];
      if (it.posted === true) { posted++; continue; }
      if (d === DECISION_APPROVE) { approve++; continue; }
      if (d === DECISION_SKIP)    { skip++;    continue; }
      if (it.status === "needs_human") { alert++; continue; }
      pending++;
    }
    return { approve, skip, alert, posted, pending, total: items.length };
  }, [items, decisions]);

  const blockers = (health && Array.isArray(health.blockers)) ? health.blockers : [];
  const hasBlockers = blockers.length > 0 || counts.alert > 0;

  return (
    <div className={`ig-health-bar ${hasBlockers ? "alert" : "ok"}`}>
      <div className="stats">
        <span className="chip">{t("admin.ig_review.stat.total")}: <b>{counts.total}</b></span>
        <span className={`chip ${counts.approve > 0 ? "green" : ""}`}>
          {t("admin.ig_review.stat.approved")}: <b>{counts.approve}</b>
        </span>
        <span className="chip muted">{t("admin.ig_review.stat.skipped")}: <b>{counts.skip}</b></span>
        <span className={`chip ${counts.alert > 0 ? "alert" : "muted"}`}>
          {t("admin.ig_review.stat.needs_human")}: <b>{counts.alert}</b>
        </span>
        <span className="chip">{t("admin.ig_review.stat.pending")}: <b>{counts.pending}</b></span>
        {counts.posted > 0 && (
          <span className="chip green">{t("admin.ig_review.stat.posted")}: <b>{counts.posted}</b></span>
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
      {(health && (health.next_due || health.last_posted_at)) && (
        <div className="meta">
          <span>
            <b>{t("admin.ig_review.health.next_due")}:</b>{" "}
            {health.next_due
              ? `D${health.next_due.day} ${health.next_due.shelf || ""} · ${_scheduledLabel(health.next_due.scheduled_for)}` +
                (_relativeFromNow(health.next_due.scheduled_for)
                  ? ` · ${_relativeFromNow(health.next_due.scheduled_for)}` : "")
              : t("admin.ig_review.health.nothing_due")}
          </span>
          <span>
            <b>{t("admin.ig_review.health.last_posted")}:</b>{" "}
            {health.last_posted_at
              ? `D${health.last_posted_day || "?"} · ${_scheduledLabel(health.last_posted_at)}`
              : t("admin.ig_review.health.never_posted")}
          </span>
          <span>
            <b>{t("admin.ig_review.health.cron")}:</b>{" "}
            {health.ig_paused ? t("admin.ig_review.health.paused") : t("admin.ig_review.health.enabled")}
          </span>
        </div>
      )}
      {blockers.length > 0 && (
        <ul className="blockers" aria-label={t("admin.ig_review.health.blockers_aria")}>
          {blockers.map((msg, i) => (
            <li key={i} className="blocker">{msg}</li>
          ))}
        </ul>
      )}
    </div>
  );
}


// ── main widget ──────────────────────────────────────────────────────

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
          <p><code>python3 -m automation.ig_queue_builder</code></p>
          {state.data.health && Array.isArray(state.data.health.blockers) && state.data.health.blockers.length > 0 && (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
              {state.data.health.blockers.map((b, i) => (
                <li key={i} style={{
                  fontSize: 13, color: "var(--accent-2)",
                  background: "oklch(0.95 0.04 25)",
                  border: "1px solid oklch(0.85 0.10 25)",
                  borderRadius: 6, padding: "8px 12px",
                  fontFamily: "var(--font-sans)",
                }}>{b}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {state.kind === "loaded" && state.data && state.data.queue && (
        <>
          <_HealthBanner
            health={state.data.health}
            items={state.data.queue.items || []}
            decisions={decisions}
          />
          <ol className="ig-review-list" aria-label={t("admin.ig_review.list_aria")}>
            {(state.data.queue.items || []).map((it) => (
              <li key={`d${it.day}-${it.shelf}`}>
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


// ── /admin grid preview tile — live dashboard ───────────────────────

export function IgReviewPreview() {
  const [state, setState] = useState({ kind: "loading", queue: null, health: null });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(QUEUE_ENDPOINT);
        const body = await r.json().catch(() => ({}));
        if (cancelled) return;
        setState({
          kind:   r.ok ? "loaded" : "error",
          queue:  body && body.queue,
          health: body && body.health,
        });
      } catch {
        if (cancelled) return;
        setState({ kind: "error", queue: null, health: null });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (state.kind === "loading") {
    return (
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-3)" }}>
        {t("admin.ig_review.preview_loading")}
      </div>
    );
  }

  if (!state.health) {
    return (
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-3)" }}>
        {t("admin.ig_review.preview_empty")}
      </div>
    );
  }

  const h = state.health;
  const localDecisions = _readDecisions();
  let localApproved = 0;
  if (state.queue && Array.isArray(state.queue.items)) {
    for (const it of state.queue.items) {
      if (localDecisions[String(it.day)] === DECISION_APPROVE) localApproved++;
    }
  }
  const effectiveApproved = Math.max(h.items_approved || 0, localApproved);
  const topBlocker = (h.blockers && h.blockers[0]) || null;

  return (
    <div className="ig-preview-tile">
      <style>{WIDGET_STYLES}</style>
      <div className="total">
        {h.items_total > 0
          ? (<><b>{h.items_total}</b> {t("admin.ig_review.preview_items")}</>)
          : t("admin.ig_review.preview_empty")}
      </div>
      <div className="row">
        <span className="good">✓ {effectiveApproved} {t("admin.ig_review.stat.approved").toLowerCase()}</span>
        {h.items_needs_human > 0 && (
          <span className="alert">⚠ {h.items_needs_human} {t("admin.ig_review.stat.needs_human").toLowerCase()}</span>
        )}
        {h.items_posted > 0 && (
          <span>↑ {h.items_posted} {t("admin.ig_review.stat.posted").toLowerCase()}</span>
        )}
      </div>
      {h.next_due && (
        <div className="row">
          <span>
            {t("admin.ig_review.health.next_due")}: <b>D{h.next_due.day}</b>{" "}
            {_relativeFromNow(h.next_due.scheduled_for) || ""}
          </span>
        </div>
      )}
      {h.last_posted_at && (
        <div className="row">
          <span>
            {t("admin.ig_review.health.last_posted")}: <b>D{h.last_posted_day || "?"}</b>{" "}
            {_relativeFromNow(h.last_posted_at) || ""}
          </span>
        </div>
      )}
      {h.ig_paused && (
        <div className="blocker">⏸ {t("admin.ig_review.health.paused")}</div>
      )}
      {topBlocker && !h.ig_paused && (
        <div className="blocker">{topBlocker}</div>
      )}
    </div>
  );
}
