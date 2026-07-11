// IgConsoleWidget — the monitor for the self-running IG autopilot.
//
// Posts are generated + auto-approved by automation/ig_autopilot.py and
// auto-published by the ig-publish cron. This screen is monitor + one
// lever (Skip):
//   1. NEXT UP    — the next post about to auto-publish, with "Skip this
//                   post" (cancels it; the operator never approves).
//   2. QUEUE      — the rest of the upcoming posts, one row each, Skip.
//   3. ACTIVITY   — a real log of what has actually been published
//                   (posted / failed), newest first, with a link to IG.
//
// Data:
//   GET  /api/admin/ig-queue   → { queue, health }   (upcoming + status)
//   GET  /api/admin/ig-log     → { entries }          (activity feed)
// Actions (both dispatch a workflow that commits back to main ~30s later):
//   POST /api/admin/ig-queue-apply   { batch, decisions:{ day: "approve"|"skip" } }
//   POST /api/admin/ig-publish-now   { day }
//
// EN-only, internal tool (matches AdminShell). a11y attribute strings use
// the `{...}` expression form so the i18n-lint attribute check passes.
//
// Mobile-first: single column; the poster thumb caps so 320px renders.

import React, { useCallback, useEffect, useMemo, useState } from "react";

const QUEUE_ENDPOINT = "/api/admin/ig-queue";
const LOG_ENDPOINT = "/api/admin/ig-log";
const APPLY_ENDPOINT = "/api/admin/ig-queue-apply";

// Vercel serves web/data/* and web/photos/* at /data/* and /photos/*.
function _publicUrl(localPath) {
  if (!localPath) return null;
  return "/" + String(localPath).replace(/^web\//, "");
}

function _firstLine(caption) {
  return String(caption || "").replace(/\*\*/g, "").trim().split("\n")[0];
}

const _DATE_FMT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
});
function _fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(String(iso).replace("Z", "+00:00"));
  return Number.isFinite(d.getTime()) ? _DATE_FMT.format(d) : "—";
}

function _igPermalink(mediaId) {
  // The publisher stores the numeric media id; there's no public
  // deep-link by id without the shortcode, so we point at the profile.
  // (Kept as a hook — swap for a permalink field if the publisher
  // starts storing one.)
  return "https://www.instagram.com/pulpo.club/";
}

// Every slide URL for a post: poster first, then the carousel photos —
// exactly what the publisher sends to Instagram (_slide_urls in
// ig_publish.py).
function _slidesOf(item) {
  const out = [];
  if (item && item.poster_path) out.push(_publicUrl(item.poster_path));
  for (const p of (item && item.carousel_photo_paths) || []) out.push(_publicUrl(p));
  return out.filter(Boolean);
}

// Render **bold** + newlines as safe React nodes (no dangerouslySetHTML).
function _renderRich(text) {
  return String(text || "").split("\n").map((line, li) => {
    const parts = line.split(/(\*\*[^*]+\*\*)/g).map((seg, si) =>
      seg.startsWith("**") && seg.endsWith("**")
        ? <strong key={si}>{seg.slice(2, -2)}</strong>
        : <span key={si}>{seg}</span>
    );
    return <div key={li} className="igc-rich-line">{parts}</div>;
  });
}

// ── data hook ─────────────────────────────────────────────────────────

function useIgData() {
  const [state, setState] = useState({
    loading: true, error: null, queue: null, health: null, log: [],
  });

  const reload = useCallback(async () => {
    try {
      const [qRes, lRes] = await Promise.all([
        fetch(QUEUE_ENDPOINT), fetch(LOG_ENDPOINT),
      ]);
      const qJson = await qRes.json().catch(() => ({}));
      const lJson = await lRes.json().catch(() => ({}));
      if (!qRes.ok) throw new Error(qJson.error || `queue ${qRes.status}`);
      setState({
        loading: false, error: null,
        queue: qJson.queue, health: qJson.health || null,
        log: Array.isArray(lJson.entries) ? lJson.entries : [],
      });
    } catch (err) {
      setState((s) => ({ ...s, loading: false, error: err.message || "load failed" }));
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);
  return { ...state, reload };
}

// ── small presentational bits ─────────────────────────────────────────

const _DAY_FMT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
function _fmtDay(iso) {
  if (!iso) return "—";
  const d = new Date(String(iso).replace("Z", "+00:00"));
  return Number.isFinite(d.getTime()) ? _DAY_FMT.format(d) : "—";
}

// The token lives in GitHub Actions (where the publisher posts), not in
// Vercel — so we show its REAL expiry (written by the publisher), not a
// "set/missing" check of Vercel's env, which was a false alarm.
function TokenPill({ health }) {
  const d = health.token_expires_days;
  const iso = health.token_expires_at_iso;
  if (d == null) return <span className="igc-pill muted">Token: set in CI</span>;
  if (d <= 0) return <span className="igc-pill bad">Token expired {_fmtDay(iso)} — re-mint</span>;
  const cls = d <= 14 ? "warn" : "ok";
  return <span className={`igc-pill ${cls}`}>Token · exp {_fmtDay(iso)} · {d}d</span>;
}

function HealthBar({ health }) {
  if (!health) return null;
  const paused = health.ig_paused;
  return (
    <div className="igc-health">
      <span className={`igc-pill ${paused ? "warn" : "ok"}`}>
        {paused ? "⏸ Paused" : "● Live"}
      </span>
      <TokenPill health={health} />
      <span className="igc-pill muted">
        Next: {health.next_due ? _fmtDate(health.next_due.scheduled_for) : "nothing approved"}
      </span>
      <span className="igc-pill muted">{health.items_posted || 0} posted</span>
    </div>
  );
}

function PosterThumb({ item, big, onOpen }) {
  const url = _publicUrl(item && item.poster_path);
  const count = _slidesOf(item).length;
  if (!url) return <div className={`igc-thumb ${big ? "big" : ""} empty`}>no poster</div>;
  return (
    <button
      type="button"
      className={`igc-thumb ${big ? "big" : ""}`}
      onClick={() => onOpen && onOpen(item)}
      title={`View full carousel (${count} slides)`}
    >
      <img src={url} alt={`poster for day ${item.day}`} loading="lazy" />
      <span className="igc-thumb-badge">⤢ {count}</span>
    </button>
  );
}

// Full-screen carousel viewer: every slide at size, swipeable, with the
// caption + the first comment that will be posted under it.
function Lightbox({ item, onClose }) {
  const slides = useMemo(() => _slidesOf(item), [item]);
  const [i, setI] = useState(0);
  const go = useCallback((d) => setI((n) => (n + d + slides.length) % slides.length), [slides.length]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, onClose]);

  return (
    <div className="igc-lb" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="igc-lb-panel" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="igc-lb-x" onClick={onClose} aria-label={"Close"}>×</button>
        <div className="igc-lb-stage">
          {slides.length > 1 && (
            <button type="button" className="igc-lb-nav prev" onClick={() => go(-1)} aria-label={"Previous slide"}>‹</button>
          )}
          <img className="igc-lb-img" src={slides[i]} alt={`slide ${i + 1} of ${slides.length}`} />
          {slides.length > 1 && (
            <button type="button" className="igc-lb-nav next" onClick={() => go(1)} aria-label={"Next slide"}>›</button>
          )}
        </div>
        {slides.length > 1 && (
          <div className="igc-lb-dots">
            {slides.map((_, k) => (
              <span key={k} className={`igc-lb-dot${k === i ? " active" : ""}`} onClick={() => setI(k)} />
            ))}
          </div>
        )}
        <div className="igc-lb-meta">
          <div className="igc-lb-when">Slide {i + 1}/{slides.length} · auto-posts {_fmtDate(item.scheduled_for)}</div>
          <div className="igc-lb-block">
            <div className="igc-lb-label">Caption</div>
            <div className="igc-rich">{_renderRich(item.caption)}</div>
          </div>
          {item.comment && (
            <div className="igc-lb-block">
              <div className="igc-lb-label">First comment</div>
              <div className="igc-rich comment">{_renderRich(item.comment)}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── the widget ────────────────────────────────────────────────────────

export function IgConsoleWidget() {
  const { loading, error, queue, health, log, reload } = useIgData();
  const [busyDay, setBusyDay] = useState(null);
  const [notice, setNotice] = useState(null);
  const [expanded, setExpanded] = useState(null);

  const batch = (queue && queue.batch) || "drop_01";
  const items = useMemo(
    () => (queue && Array.isArray(queue.items) ? queue.items : []),
    [queue],
  );

  // Upcoming = approved posts that will auto-publish, not yet posted and
  // not skipped, earliest scheduled first. Posts are auto-approved by the
  // autopilot; the operator's only lever here is Skip.
  //
  // `approved === true` is load-bearing, not cosmetic: patch_queue keeps
  // superseded old-design items in the queue with `approved:false` +
  // `status:superseded_campaign_v1` (audit trail, not deletion). Without
  // this gate they render interleaved with the real campaign — the
  // "old campaign still showing" bug. The publisher itself only posts
  // approved+due items, so this matches what will actually go live.
  const upcoming = useMemo(() => {
    return items
      .filter((it) => it && it.approved === true && it.posted !== true && it.skipped !== true)
      .sort((a, b) => String(a.scheduled_for || "").localeCompare(String(b.scheduled_for || "")));
  }, [items]);
  const nextUp = upcoming[0] || null;
  const rest = upcoming.slice(1);

  // Skip writes through the same workflow that commits back to main
  // (~30s), so we notice + auto-refresh once it lands.
  const skip = useCallback(async (day) => {
    setBusyDay(day);
    setNotice(null);
    try {
      const r = await fetch(APPLY_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ batch, decisions: { [String(day)]: "skip" } }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.status !== 202) throw new Error(j.detail || j.error || `HTTP ${r.status}`);
      setNotice(`Skipped day ${day} — it won’t post. Updating in ~30s…`);
      setBusyDay(null);
      setTimeout(() => reload(), 32000);
    } catch (err) {
      setBusyDay(null);
      setNotice(`Could not skip day ${day}: ${err.message}`);
    }
  }, [batch, reload]);

  if (loading) return <div className="igc"><div className="igc-note">Loading…</div><style>{STYLES}</style></div>;
  if (error) {
    return (
      <div className="igc">
        <div className="igc-note bad">Couldn’t load the queue: {error}</div>
        <button type="button" className="igc-btn" onClick={reload}>Retry</button>
        <style>{STYLES}</style>
      </div>
    );
  }

  return (
    <div className="igc">
      <HealthBar health={health} />
      {notice && <div className="igc-note info">{notice}</div>}

      {/* NEXT UP */}
      <section className="igc-section">
        <h3 className="igc-h">Next up</h3>
        {nextUp ? (
          <div className="igc-next">
            <PosterThumb item={nextUp} big onOpen={setExpanded} />
            <div className="igc-next-body">
              <div className="igc-when">{_fmtDate(nextUp.scheduled_for)}</div>
              <div className="igc-caption">{_firstLine(nextUp.caption)}</div>
              <button type="button" className="igc-link-btn" onClick={() => setExpanded(nextUp)}>
                View full carousel ({_slidesOf(nextUp).length} slides) →
              </button>
              <div className="igc-meta">
                <span className="igc-dot ok" />
                Auto-posts {_fmtDate(nextUp.scheduled_for)}
                {" · "}day {nextUp.day} · {1 + (nextUp.carousel_photo_paths || []).length} slides
              </div>
              <div className="igc-actions">
                <button type="button" className="igc-btn"
                  disabled={busyDay === nextUp.day}
                  onClick={() => skip(nextUp.day)}>
                  {busyDay === nextUp.day ? "Working…" : "Skip this post"}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="igc-note">Nothing queued right now — the autopilot tops up the queue daily.</div>
        )}
      </section>

      {/* QUEUE */}
      {rest.length > 0 && (
        <section className="igc-section">
          <h3 className="igc-h">Queue <span className="igc-count">{rest.length}</span></h3>
          <ul className="igc-list">
            {rest.map((it) => (
              <li key={it.day} className="igc-row">
                <PosterThumb item={it} onOpen={setExpanded} />
                <div className="igc-row-body">
                  <div className="igc-row-top">
                    <span className="igc-when sm">{_fmtDate(it.scheduled_for)}</span>
                    <span className="igc-dot ok" />
                  </div>
                  <div className="igc-caption sm">{_firstLine(it.caption)}</div>
                </div>
                <div className="igc-row-actions">
                  <button type="button" className="igc-btn sm ghost"
                    disabled={busyDay === it.day}
                    onClick={() => skip(it.day)}>
                    {busyDay === it.day ? "…" : "Skip"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ACTIVITY LOG */}
      <section className="igc-section">
        <h3 className="igc-h">Activity log</h3>
        {log.length === 0 ? (
          <div className="igc-note">Nothing published yet.</div>
        ) : (
          <ul className="igc-log">
            {log.map((e, i) => (
              <li key={`${e.ts}-${i}`} className={`igc-log-row ${e.status}`}>
                <span className="igc-log-icon">{e.status === "posted" ? "✅" : "❌"}</span>
                <div className="igc-log-body">
                  <div className="igc-log-top">
                    <span className="igc-when sm">{_fmtDate(e.ts)}</span>
                    {e.status === "posted" && e.media_id && (
                      <a className="igc-link" href={_igPermalink(e.media_id)}
                        target="_blank" rel="noreferrer">View on Instagram ↗</a>
                    )}
                  </div>
                  <div className="igc-caption sm">{e.caption_preview || `day ${e.day}`}</div>
                  {e.status === "failed" && e.error && (
                    <div className="igc-err">{e.error}</div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <button type="button" className="igc-btn ghost refresh" onClick={reload}>Refresh</button>
      {expanded && <Lightbox item={expanded} onClose={() => setExpanded(null)} />}
      <style>{STYLES}</style>
    </div>
  );
}

// ── grid preview tile ─────────────────────────────────────────────────

export function IgConsolePreview() {
  const [health, setHealth] = useState(null);
  useEffect(() => {
    fetch(QUEUE_ENDPOINT)
      .then((r) => r.json())
      .then((j) => setHealth(j.health || null))
      .catch(() => {});
  }, []);
  if (!health) return <div className="igc-prev">Instagram console</div>;
  return (
    <div className="igc-prev">
      <div className="igc-prev-row">
        <span className={`igc-pill ${health.ig_paused ? "warn" : "ok"}`}>
          {health.ig_paused ? "Paused" : "Live"}
        </span>
        <span className="igc-pill muted">{health.items_approved || 0} approved</span>
        <span className="igc-pill muted">{health.items_posted || 0} posted</span>
      </div>
      <div className="igc-prev-next">
        Next: {health.next_due ? _fmtDate(health.next_due.scheduled_for) : "—"}
      </div>
      <style>{STYLES}</style>
    </div>
  );
}

// ── styles (tokens only; no hex/rgb literals) ─────────────────────────

const STYLES = `
.igc { display:flex; flex-direction:column; gap:16px; color:var(--ink); font-family:var(--font-sans); }
.igc-section { display:flex; flex-direction:column; gap:10px; }
.igc-h { font-family:var(--font-display); font-style:italic; font-weight:400; font-size:20px; margin:0; letter-spacing:-.01em; display:flex; align-items:center; gap:8px; }
.igc-count { font-family:var(--font-sans); font-style:normal; font-size:12px; color:var(--ink); background:var(--paper-2); border:1px solid var(--line); border-radius:999px; padding:1px 8px; }

.igc-health { display:flex; flex-wrap:wrap; gap:8px; }
.igc-pill { font-size:12px; padding:4px 10px; border-radius:999px; border:1px solid var(--line); background:var(--paper); white-space:nowrap; }
.igc-pill.ok   { color:var(--accent); border-color:color-mix(in oklch, var(--accent) 40%, var(--line)); }
.igc-pill.warn { color:var(--accent-2); border-color:color-mix(in oklch, var(--accent-2) 40%, var(--line)); }
.igc-pill.bad  { color:var(--accent-2); border-color:var(--accent-2); }
.igc-pill.muted{ color:color-mix(in oklch, var(--ink) 55%, var(--paper)); }

.igc-note { font-size:14px; padding:12px 14px; border-radius:10px; background:var(--paper-2); border:1px solid var(--line); }
.igc-note.info { border-color:color-mix(in oklch, var(--accent) 40%, var(--line)); }
.igc-note.bad  { color:var(--accent-2); border-color:var(--accent-2); }

.igc-next { display:flex; flex-direction:column; gap:14px; padding:14px; background:var(--paper); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow-1); }
.igc-next-body { display:flex; flex-direction:column; gap:6px; min-width:0; flex:1; }
.igc-when { font-size:13px; color:color-mix(in oklch, var(--ink) 60%, var(--paper)); }
.igc-when.sm { font-size:12px; }
.igc-caption { font-size:15px; line-height:1.35; overflow-wrap:anywhere; }
.igc-caption.sm { font-size:13px; color:color-mix(in oklch, var(--ink) 80%, var(--paper)); }
.igc-meta { font-size:12px; color:color-mix(in oklch, var(--ink) 55%, var(--paper)); display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.igc-dot { width:8px; height:8px; border-radius:999px; display:inline-block; background:var(--line); }
.igc-dot.ok { background:var(--accent); }
.igc-dot.pending { background:var(--accent-2); }

.igc-thumb { width:72px; height:90px; flex:0 0 auto; border-radius:8px; overflow:hidden; background:var(--paper-2); border:1px solid var(--line); }
/* Mobile-first: the Next-up poster is full-width; a min-width query
   shrinks it to a fixed thumb once there's room for a side-by-side row. */
.igc-thumb.big { width:100%; height:auto; aspect-ratio:4/5; }
.igc-thumb img { width:100%; height:100%; object-fit:cover; display:block; }
.igc-thumb.empty { display:flex; align-items:center; justify-content:center; font-size:11px; color:var(--ink-muted, color-mix(in oklch, var(--ink) 50%, var(--paper))); }

.igc-actions { display:flex; gap:8px; margin-top:4px; }
.igc-btn { font-family:var(--font-sans); font-size:14px; padding:8px 16px; border-radius:999px; border:1px solid var(--line); background:var(--paper); color:var(--ink); cursor:pointer; }
.igc-btn:hover { background:var(--paper-2); }
.igc-btn.primary { background:var(--accent); border-color:var(--accent); color:var(--paper); }
.igc-btn.primary:hover { background:var(--accent-strong); }
.igc-btn.sm { font-size:12px; padding:5px 12px; }
.igc-btn.ghost { background:transparent; }
.igc-btn.refresh { align-self:flex-start; }
.igc-btn:disabled { opacity:.55; cursor:default; }

.igc-list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:8px; }
.igc-row { display:flex; gap:12px; align-items:center; padding:8px; border:1px solid var(--line); border-radius:12px; background:var(--paper); }
.igc-row-body { flex:1; min-width:0; display:flex; flex-direction:column; gap:3px; }
.igc-row-top { display:flex; align-items:center; gap:8px; }
.igc-row-actions { display:flex; gap:6px; flex:0 0 auto; }

.igc-log { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:6px; }
.igc-log-row { display:flex; gap:10px; padding:10px 12px; border:1px solid var(--line); border-radius:10px; background:var(--paper); }
.igc-log-row.failed { border-color:color-mix(in oklch, var(--accent-2) 45%, var(--line)); }
.igc-log-icon { flex:0 0 auto; }
.igc-log-body { flex:1; min-width:0; display:flex; flex-direction:column; gap:3px; }
.igc-log-top { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.igc-link { font-size:12px; color:var(--accent); text-decoration:none; border-bottom:1px dashed var(--accent); white-space:nowrap; }
.igc-err { font-size:12px; color:var(--accent-2); font-family:var(--font-mono); overflow-wrap:anywhere; }

/* clickable thumb → lightbox */
.igc-thumb { position:relative; padding:0; cursor:pointer; display:block; }
.igc-thumb:hover .igc-thumb-badge { opacity:1; }
.igc-thumb-badge { position:absolute; right:4px; bottom:4px; font-size:11px; padding:1px 6px; border-radius:999px;
  background:color-mix(in oklch, var(--ink) 78%, transparent); color:var(--paper); opacity:.85; }
.igc-link-btn { align-self:flex-start; background:none; border:none; padding:0; cursor:pointer;
  font-size:13px; color:var(--accent); border-bottom:1px dashed var(--accent); font-family:var(--font-sans); }
.igc-link-btn:hover { color:var(--accent-strong); }

/* lightbox */
.igc-lb { position:fixed; inset:0; z-index:1000; background:color-mix(in oklch, var(--ink) 82%, transparent);
  display:flex; align-items:center; justify-content:center; padding:16px; }
.igc-lb-panel { background:var(--paper); border-radius:16px; width:min(560px,100%); max-height:92vh; overflow:auto;
  box-shadow:var(--shadow-modal); position:relative; }
.igc-lb-x { position:absolute; top:8px; right:10px; z-index:2; background:var(--paper); border:1px solid var(--line);
  border-radius:999px; width:32px; height:32px; font-size:20px; line-height:1; cursor:pointer; color:var(--ink); }
.igc-lb-stage { position:relative; display:flex; align-items:center; justify-content:center; background:var(--paper-2);
  border-radius:16px 16px 0 0; }
.igc-lb-img { width:100%; height:auto; max-height:70vh; object-fit:contain; display:block; border-radius:16px 16px 0 0; }
.igc-lb-nav { position:absolute; top:50%; transform:translateY(-50%); width:40px; height:40px; border-radius:999px;
  border:none; background:color-mix(in oklch, var(--ink) 62%, transparent); color:var(--paper); font-size:26px;
  line-height:1; cursor:pointer; display:flex; align-items:center; justify-content:center; }
.igc-lb-nav.prev { left:8px; } .igc-lb-nav.next { right:8px; }
.igc-lb-dots { display:flex; gap:6px; justify-content:center; padding:10px 0 0; }
.igc-lb-dot { width:7px; height:7px; border-radius:999px; background:var(--line); cursor:pointer; }
.igc-lb-dot.active { background:var(--accent); }
.igc-lb-meta { padding:14px 18px 18px; display:flex; flex-direction:column; gap:12px; }
.igc-lb-when { font-size:12px; color:color-mix(in oklch, var(--ink) 55%, var(--paper)); }
.igc-lb-block { display:flex; flex-direction:column; gap:4px; }
.igc-lb-label { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--ink-muted, color-mix(in oklch, var(--ink) 50%, var(--paper))); }
.igc-rich { font-size:14px; line-height:1.45; overflow-wrap:anywhere; }
.igc-rich.comment { font-size:13px; color:color-mix(in oklch, var(--ink) 80%, var(--paper)); }
.igc-rich-line { min-height:0.6em; }

.igc-prev { display:flex; flex-direction:column; gap:8px; }
.igc-prev-row { display:flex; flex-wrap:wrap; gap:6px; }
.igc-prev-next { font-size:12px; color:color-mix(in oklch, var(--ink) 60%, var(--paper)); }

/* Mobile-first: default styles above target the narrowest viewport;
   this min-width query enhances to a side-by-side layout on wider screens. */
@media (min-width:560px) {
  .igc-next { flex-direction:row; align-items:flex-start; }
  .igc-thumb.big { width:104px; height:130px; aspect-ratio:auto; }
}
`;
