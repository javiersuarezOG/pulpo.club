// Email-first "start free" modal. Shown to ANONYMOUS visitors hitting any
// gated action (open a top-3, save, hero lock). Mirrors the home-hero email
// capture — just an email, no account, no card — and turns the visitor into
// a Free member who can open this week's top 3 in full. The Go-Pro upsell is
// a secondary link, not the primary action (that's the funnel inversion).
//
// cfg = { reason: "top3" | "listing" | "save" | "gate", listingId?: string }.
// On success we call app.becomeFreeMember (which opens the stashed top-3),
// then close.

import React, { useEffect, useRef, useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { Icon, PulpoMark } from "../components.jsx";
import { subscribeEmail, NL_EMAIL_RE } from "../lib/newsletter-signup";

/**
 * @param {object} props
 * @param {object} props.app    — App state (becomeFreeMember, openFreeMonthModal).
 * @param {string} props.locale
 * @param {{reason?: string, listingId?: string|null}} props.cfg
 * @param {() => void} props.onClose
 */
export function EmailCaptureModal({ app, locale: lc, cfg, onClose }) {
  const dialogRef = useRef(null);
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle"); // idle | loading | invalid | error
  const reason = (cfg && cfg.reason) || "gate";

  useEffect(() => {
    try { track("email_capture.shown", { reason }); } catch { /* ignore */ }
    if (dialogRef.current) dialogRef.current.focus();
  }, [reason]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") dismiss("escape"); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const dismiss = (action) => {
    try { track("email_capture.dismissed", { reason, action }); } catch { /* ignore */ }
    onClose();
  };

  const submit = async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const value = email.trim();
    if (!NL_EMAIL_RE.test(value)) { setStatus("invalid"); return; }
    setStatus("loading");
    const domain = value.split("@")[1] || "";
    const result = await subscribeEmail(value, { source: `email_capture_${reason}`, locale: lc });
    try { track("email_capture.submitted", { reason, email_domain_only: domain, result: result.kind }); } catch { /* ignore */ }
    if (result.kind === "success" || result.kind === "already") {
      try { track("free_member_created", { reason, via: "email_capture" }); } catch { /* ignore */ }
      // Become a Free member; opens the stashed top-3 (if any) once state
      // lands, and fires the app-level JoinCelebration reveal.
      app.becomeFreeMember({ email: value, openListingId: reason === "top3" ? (cfg && cfg.listingId) || null : null, returning: result.kind === "already" });
      onClose();
      return;
    }
    setStatus(result.kind === "invalid" ? "invalid" : "error");
  };

  const goPro = () => {
    try { track("email_capture.go_pro_clicked", { reason }); } catch { /* ignore */ }
    onClose();
    if (typeof app.openFreeMonthModal === "function") app.openFreeMonthModal({ trigger: "browse_card" });
  };

  return (
    <div className="modal-backdrop" role="presentation" onClick={() => dismiss("backdrop")}>
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={t("email_capture.aria.dialog", lc)}
        className="modal email-capture-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="modal-close"
          onClick={() => dismiss("close_button")}
          aria-label={t("email_capture.aria.close", lc)}
        >
          <Icon name="close" size={18} />
        </button>

        <div className="modal-brand-mark" style={{ color: "var(--accent)" }}>
          <PulpoMark size={36} />
        </div>
        <h2 className="free-month-modal-headline">{t("email_capture.headline", lc)}</h2>
        <p className="free-month-modal-body">{t("email_capture.body", lc)}</p>

        <ul className="free-month-modal-bullets">
          <li><span className="free-month-modal-bullet-mark" aria-hidden="true">✓</span> {t("email_capture.bullet.1", lc)}</li>
          <li><span className="free-month-modal-bullet-mark" aria-hidden="true">✓</span> {t("email_capture.bullet.2", lc)}</li>
          <li><span className="free-month-modal-bullet-mark" aria-hidden="true">✓</span> {t("email_capture.bullet.3", lc)}</li>
        </ul>

        <form className="hv6-signup" onSubmit={submit} noValidate>
          <input
            type="email"
            className="hv6-signup-input"
            placeholder={t("email_capture.placeholder", lc)}
            aria-label={t("email_capture.aria.email", lc)}
            value={email}
            onChange={(e) => { setEmail(e.target.value); if (status !== "idle" && status !== "loading") setStatus("idle"); }}
            disabled={status === "loading"}
            autoFocus
          />
          <button type="submit" className="hv6-signup-btn" disabled={status === "loading"}>
            {t(status === "loading" ? "email_capture.cta_loading" : "email_capture.cta", lc)}
          </button>
        </form>
        {(status === "invalid" || status === "error") && (
          <p className="free-month-modal-error" role="alert">
            {t(status === "invalid" ? "email_capture.invalid" : "email_capture.error", lc)}
          </p>
        )}

        <button type="button" className="link-btn email-capture-go-pro" onClick={goPro}>
          {t("email_capture.go_pro", lc)}
        </button>
        <button type="button" className="free-month-modal-dismiss link-btn" onClick={() => dismiss("not_now")}>
          {t("email_capture.dismiss", lc)}
        </button>
      </div>
    </div>
  );
}
