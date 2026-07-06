// IgConsoleWidget — the simple operator console for Instagram.
//
// Replaces the dense IgReviewWidget with one screen that answers three
// questions at a glance:
//   1. NEXT UP    — the next post about to go out, with Post now / Approve.
//   2. QUEUE      — the upcoming posts, one row each, approve/skip inline.
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
const PUBLISH_NOW_ENDPOINT = "/api/admin/ig-publish-now";

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

function HealthBar({ health }) {
  if (!health) return null;
  const paused = health.ig_paused;
  const tokenOk = health.ig_user_id_set && health.ig_token_set;
  return (
    <div className="igc-health">
      <span className={`igc-pill ${paused ? "warn" : "ok"}`}>
        {paused ? "⏸ Paused" : "● Live"}
      </span>
      <span className={`igc-pill ${tokenOk ? "ok" : "bad"}`}>
        {tokenOk ? "Token set" : "Token missing"}
      </span>
      <span className="igc-pill muted">
        Next: {health.next_due ? _fmtDate(health.next_due.scheduled_for) : "nothing approved"}
      </span>
      <span className="igc-pill muted">{health.items_posted || 0} posted</span>
    </div>
  );
}

function PosterThumb({ item, big }) {
  const url = _publicUrl(item && item.poster_path);
  if (!url) return <div className={`igc-thumb ${big ? "big" : ""} empty`}>no poster</div>;
  return (
    <div className={`igc-thumb ${big ? "big" : ""}`}>
      <img src={url} alt={`poster for day ${item.day}`} loading="lazy" />
    </div>
  );
}

// ── the widget ────────────────────────────────────────────────────────

export function IgConsoleWidget() {
  const { loading, error, queue, health, log, reload } = useIgData();
  const [busyDay, setBusyDay] = useState(null);
  const [notice, setNotice] = useState(null);

  const batch = (queue && queue.batch) || "drop_01";
  const items = useMemo(
    () => (queue && Array.isArray(queue.items) ? queue.items : []),
    [queue],
  );

  // Upcoming = not yet posted, earliest scheduled first.
  const upcoming = useMemo(() => {
    return items
      .filter((it) => it && it.posted !== true)
      .sort((a, b) => String(a.scheduled_for || "").localeCompare(String(b.scheduled_for || "")));
  }, [items]);
  const nextUp = upcoming[0] || null;
  const rest = upcoming.slice(1);

  // After a dispatch the workflow commits ~30s later — schedule a refresh
  // so the operator sees the new state without a manual reload.
  const afterDispatch = useCallback((msg) => {
    setNotice(msg);
    setBusyDay(null);
    setTimeout(() => reload(), 32000);
  }, [reload]);

  const decide = useCallback(async (day, decision) => {
    setBusyDay(day);
    setNotice(null);
    try {
      const r = await fetch(APPLY_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ batch, decisions: { [String(day)]: decision } }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.status !== 202) throw new Error(j.detail || j.error || `HTTP ${r.status}`);
      afterDispatch(`${decision === "approve" ? "Approved" : "Skipped"} day ${day} — updating in ~30s…`);
    } catch (err) {
      setBusyDay(null);
      setNotice(`Could not ${decision} day ${day}: ${err.message}`);
    }
  }, [batch, afterDispatch]);

  const publishNow = useCallback(async (day) => {
    setBusyDay(day);
    setNotice(null);
    try {
      const r = await fetch(PUBLISH_NOW_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ day }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.status !== 202) throw new Error(j.detail || j.hint || j.error || `HTTP ${r.status}`);
      afterDispatch(`Publishing day ${day} now — it appears on Instagram in ~30–60s.`);
    } catch (err) {
      setBusyDay(null);
      setNotice(`Could not publish day ${day}: ${err.message}`);
    }
  }, [afterDispatch]);

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
            <PosterThumb item={nextUp} big />
            <div className="igc-next-body">
              <div className="igc-when">{_fmtDate(nextUp.scheduled_for)}</div>
              <div className="igc-caption">{_firstLine(nextUp.caption)}</div>
              <div className="igc-meta">
                <span className={`igc-dot ${nextUp.approved ? "ok" : "pending"}`} />
                {nextUp.approved ? "Approved" : "Needs approval"}
                {" · "}day {nextUp.day} · {1 + (nextUp.carousel_photo_paths || []).length} slides
              </div>
              <div className="igc-actions">
                {nextUp.approved ? (
                  <button type="button" className="igc-btn primary"
                    disabled={busyDay === nextUp.day}
                    onClick={() => publishNow(nextUp.day)}>
                    {busyDay === nextUp.day ? "Working…" : "Post now"}
                  </button>
                ) : (
                  <button type="button" className="igc-btn primary"
                    disabled={busyDay === nextUp.day}
                    onClick={() => decide(nextUp.day, "approve")}>
                    {busyDay === nextUp.day ? "Working…" : "Approve"}
                  </button>
                )}
                <button type="button" className="igc-btn"
                  disabled={busyDay === nextUp.day}
                  onClick={() => decide(nextUp.day, "skip")}>
                  Skip
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="igc-note">Nothing queued. Generate the next posts to fill the queue.</div>
        )}
      </section>

      {/* QUEUE */}
      {rest.length > 0 && (
        <section className="igc-section">
          <h3 className="igc-h">Queue <span className="igc-count">{rest.length}</span></h3>
          <ul className="igc-list">
            {rest.map((it) => (
              <li key={it.day} className="igc-row">
                <PosterThumb item={it} />
                <div className="igc-row-body">
                  <div className="igc-row-top">
                    <span className="igc-when sm">{_fmtDate(it.scheduled_for)}</span>
                    <span className={`igc-dot ${it.approved ? "ok" : "pending"}`} />
                  </div>
                  <div className="igc-caption sm">{_firstLine(it.caption)}</div>
                </div>
                <div className="igc-row-actions">
                  {!it.approved && (
                    <button type="button" className="igc-btn sm"
                      disabled={busyDay === it.day}
                      onClick={() => decide(it.day, "approve")}>
                      {busyDay === it.day ? "…" : "Approve"}
                    </button>
                  )}
                  <button type="button" className="igc-btn sm ghost"
                    disabled={busyDay === it.day}
                    onClick={() => decide(it.day, "skip")}>
                    Skip
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

.igc-next { display:flex; gap:14px; padding:14px; background:var(--paper); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow-1); }
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
.igc-thumb.big { width:104px; height:130px; }
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

.igc-prev { display:flex; flex-direction:column; gap:8px; }
.igc-prev-row { display:flex; flex-wrap:wrap; gap:6px; }
.igc-prev-next { font-size:12px; color:color-mix(in oklch, var(--ink) 60%, var(--paper)); }

@media (max-width:520px) {
  .igc-next { flex-direction:column; }
  .igc-thumb.big { width:100%; height:auto; aspect-ratio:4/5; }
}
`;
