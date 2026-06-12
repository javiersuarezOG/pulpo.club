// AccessModal — the single modal that replaces the separate email-capture
// and Pro modals. Shows a contextual headline + the shared AccessBlock
// (whose options come from the registry for this surface). Anonymous gated
// actions use surface "gate_anon" (all three options); a Free member hitting
// a Pro gate uses "gate_member" (Go Pro / Sign in).

import React, { useEffect, useRef } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { Icon, PulpoMark } from "../components.jsx";
import { AccessBlock } from "./AccessBlock.jsx";

/**
 * @param {object} props
 * @param {object} props.app
 * @param {string} props.locale
 * @param {{surface: import("../config/access").AccessSurface, reason?: string, listingId?: string|null}} props.cfg
 * @param {() => void} props.onClose
 */
export function AccessModal({ app, locale: lc, cfg, onClose }) {
  const dialogRef = useRef(null);
  const surface = (cfg && cfg.surface) || "gate_anon";
  const reason = (cfg && cfg.reason) || surface;

  useEffect(() => {
    try { track("access_modal.shown", { surface, reason }); } catch { /* ignore */ }
    if (dialogRef.current) dialogRef.current.focus();
  }, [surface, reason]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") dismiss("escape"); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const dismiss = (action) => {
    try { track("access_modal.dismissed", { surface, reason, action }); } catch { /* ignore */ }
    onClose();
  };

  // Contextual headline: a Free member reaching for Pro sees the upsell
  // framing; everyone else sees the "your top 3 are ready" framing.
  const titleKey = surface === "gate_member" ? "access.modal.gopro.title" : "access.modal.top3.title";
  const leadKey = surface === "gate_member" ? "access.modal.gopro.lead" : "access.modal.top3.lead";

  return (
    <div className="modal-backdrop" role="presentation" onClick={() => dismiss("backdrop")}>
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={t("access.modal.aria", lc)}
        className="modal access-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" className="modal-close" onClick={() => dismiss("close_button")} aria-label={t("access.modal.aria.close", lc)}>
          <Icon name="close" size={18} />
        </button>
        <div className="modal-brand-mark" style={{ color: "var(--accent)" }}>
          <PulpoMark size={36} />
        </div>
        <h2 className="access-modal-title">{t(titleKey, lc)}</h2>
        <p className="access-modal-lead">{t(leadKey, lc)}</p>
        <AccessBlock app={app} locale={lc} surface={surface} cfg={cfg} onDone={onClose} />
      </div>
    </div>
  );
}
