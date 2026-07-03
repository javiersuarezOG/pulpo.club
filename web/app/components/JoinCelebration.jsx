// JoinCelebration — the branded "you're in" moment shown on EVERY free-signup
// success, from any surface (home hero, favorites/discover/save gates, listing
// deep-links). Rendered once at app level and fired from the single
// `becomeFreeMember` choke point, so it can never be missed by a flow and
// never needs re-wiring per component.
//
// The reveal: the Pulpo octopus squirts its ink, rises out of it, and hands
// over this week's top 3 — a deliberately single-look deep-sea scene (it stays
// dark-green in both themes; it's a moment, not a document). Auto-dismisses,
// and is dismissible by tap / Escape / the CTA. Fully reduced-motion safe.
//
// Colors come from CSS tokens: the octopus/text via classes in index.css, the
// canvas ink + bubbles via the `--jc-ink` / `--jc-bubble` custom properties
// read off the panel (no color literals in JS).

import React, { useCallback, useEffect, useRef } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";

export function JoinCelebration({ locale: lc, returning = false, onDone }) {
  const panelRef = useRef(null);
  const canvasRef = useRef(null);

  const done = useCallback(() => { if (typeof onDone === "function") onDone(); }, [onDone]);

  // Focus, auto-dismiss, Escape.
  useEffect(() => {
    try { track("free_join_celebration.shown", { returning }); } catch { /* ignore */ }
    if (panelRef.current) panelRef.current.focus();
    const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const timer = setTimeout(done, reduce ? 2600 : 4200);
    const onKey = (e) => { if (e.key === "Escape") done(); };
    window.addEventListener("keydown", onKey);
    return () => { clearTimeout(timer); window.removeEventListener("keydown", onKey); };
  }, [done, returning]);

  // Ink squirt + rising bubbles on a canvas sized to the panel.
  useEffect(() => {
    const canvas = canvasRef.current, panel = panelRef.current;
    if (!canvas || !panel) return;
    const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return; // static end-state under reduced motion
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const cs = getComputedStyle(panel);
    const inkColor = (cs.getPropertyValue("--jc-ink") || "").trim() || "rgba(9,44,29,0.9)"; // token-exception: canvas fallback if var unresolved
    const bubbleColor = (cs.getPropertyValue("--jc-bubble") || "").trim() || "rgba(180,230,205,0.16)"; // token-exception: canvas fallback

    const dpr = Math.min(typeof devicePixelRatio === "number" ? devicePixelRatio : 1, 2);
    let W = 0, H = 0, raf = 0, start = 0;
    const parts = [], bubbles = [];

    const size = () => {
      const r = panel.getBoundingClientRect();
      W = r.width; H = r.height;
      canvas.width = Math.max(1, W * dpr); canvas.height = Math.max(1, H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const seed = () => {
      for (let i = 0; i < 26; i++) {
        // vary by index (Math.random ok in browser; deterministic not required)
        const a = -Math.PI / 2 + (Math.random() - 0.5) * 1.7;
        const s = 2.6 + Math.random() * 4.4;
        parts.push({ x: W * 0.5 + (Math.random() - 0.5) * 46, y: H - 12, vx: Math.cos(a) * s, vy: Math.sin(a) * s - 2, r: 3 + Math.random() * 7, life: 1, drift: (Math.random() - 0.5) * 0.4 });
      }
      for (let b = 0; b < 14; b++) {
        bubbles.push({ x: Math.random() * W, y: H + Math.random() * H, r: 1.5 + Math.random() * 4, sp: 0.3 + Math.random() * 0.9, ph: Math.random() * 6.28 });
      }
    };
    const frame = (ts) => {
      if (!start) start = ts;
      const elapsed = (ts - start) / 1000;
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = bubbleColor;
      bubbles.forEach((bb) => {
        bb.y -= bb.sp; bb.x += Math.sin(ts / 700 + bb.ph) * 0.25;
        if (bb.y < -8) { bb.y = H + 8; bb.x = Math.random() * W; }
        ctx.beginPath(); ctx.arc(bb.x, bb.y, bb.r, 0, 6.283); ctx.fill();
      });
      ctx.fillStyle = inkColor;
      parts.forEach((p) => {
        if (p.life <= 0) return;
        p.vy += 0.16; p.x += p.vx + p.drift; p.y += p.vy; p.life -= 0.018; p.r *= 0.985;
        ctx.globalAlpha = Math.max(0, p.life);
        ctx.beginPath(); ctx.arc(p.x, p.y, Math.max(0, p.r), 0, 6.283); ctx.fill();
      });
      ctx.globalAlpha = 1;
      if (elapsed < 6) raf = requestAnimationFrame(frame);
    };

    size(); seed(); raf = requestAnimationFrame(frame);
    const onResize = () => size();
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, []);

  return (
    <div className="jc-backdrop" role="presentation" onClick={done}>
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={t("access.join.aria", lc)}
        className="jc-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <canvas ref={canvasRef} className="jc-ink" aria-hidden="true" />
        <button type="button" className="jc-close" aria-label={t("access.join.aria.close", lc)} onClick={done}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></svg>
        </button>

        <div className="jc-stage">
          <div className="jc-scene">
          <div className="jc-octo">
            <div className="jc-octo-rise"><div className="jc-octo-body">
              <svg viewBox="0 0 120 116" width="128" height="124" aria-hidden="true">
                {/* tentacles */}
                <g className="jc-tent-fill">
                  <path className="jc-tent a" d="M40 58c-10 4-20 10-22 22-1 7 3 12 8 12 6 0 7-6 6-12-1-8 2-14 12-16z" />
                  <path className="jc-tent b" d="M52 62c-6 8-9 18-6 28 2 6 8 7 11 3 3-5 0-10-1-16-1-6 0-11 4-16z" />
                  <path className="jc-tent c" d="M68 62c6 8 9 18 6 28-2 6-8 7-11 3-3-5 0-10 1-16 1-6 0-11-4-16z" />
                  <path className="jc-tent d" d="M80 58c10 4 20 10 22 22 1 7-3 12-8 12-6 0-7-6-6-12 1-8-2-14-12-16z" />
                  <path className="jc-tent a jc-tent-back" d="M46 60c-4 9-4 20 0 30 2 5 7 5 9 1 2-5-1-9-2-15-1-6-1-11 1-17z" />
                  <path className="jc-tent d jc-tent-back" d="M74 60c4 9 4 20 0 30-2 5-7 5-9 1-2-5 1-9 2-15 1-6 1-11-1-17z" />
                </g>
                {/* head */}
                <ellipse className="jc-head" cx="60" cy="42" rx="30" ry="32" />
                <ellipse className="jc-head-hi" cx="50" cy="30" rx="9" ry="7" />
                {/* eyes */}
                <circle className="jc-eye" cx="50" cy="44" r="7.5" />
                <circle className="jc-pupil" cx="51.5" cy="45" r="3.4" />
                <circle className="jc-eye" cx="71" cy="44" r="7.5" />
                <circle className="jc-pupil" cx="72.5" cy="45" r="3.4" />
                <circle className="jc-glint" cx="49.5" cy="42.5" r="1.1" />
                <circle className="jc-glint" cx="70.5" cy="42.5" r="1.1" />
                <path className="jc-smile" d="M55 57c2.4 2.6 7.6 2.6 10 0" fill="none" />
                <circle className="jc-blush" cx="43" cy="52" r="3" />
                <circle className="jc-blush" cx="78" cy="52" r="3" />
              </svg>
            </div></div>
          </div>

          <div className="jc-picks" aria-hidden="true">
            <div className="jc-pick p1"><i /><span className="jc-grade">A</span></div>
            <div className="jc-pick p2"><i /><span className="jc-grade">A−</span></div>
            <div className="jc-pick p3"><i /><span className="jc-grade">B+</span></div>
          </div>
          </div>

          <h2 className="jc-title">{t(returning ? "access.join.back_title" : "access.join.title", lc)}</h2>
          <p className="jc-body">{t("access.join.body", lc)}</p>
          <button type="button" className="jc-cta" onClick={done}>{t("access.join.cta", lc)}</button>
        </div>
      </div>
    </div>
  );
}
