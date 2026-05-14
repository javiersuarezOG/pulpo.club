// Wave-5 USP popup. Replaces the inline USPBand on the homepage with a
// triggered modal. The 3 cards' content + i18n keys are lifted directly
// from USPBand.jsx so the wording stays consistent.
//
// Trigger plumbing lives in lib/usp-popup-trigger.ts. This component
// owns presentation + dismiss UX + CTA dispatch only.
//
// Pattern: modeled after ProUpsellModal (pages.jsx) — backdrop + dialog
// with focus management, Escape/backdrop/close-button/Maybe-later
// dismiss paths, all four routed through the same `dismiss(action)`
// helper so the telemetry shape stays uniform.

import React, { useEffect, useRef } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import {
  Icon,
  PulpoLogo,
} from "../components.jsx";
import {
  IconLock,
  IconMailFast,
  IconListSearch,
  IconMapPinHeart,
} from "../home/icons.jsx";
import { markUspPopupDismissed } from "../lib/usp-popup-trigger";
import { routeCtaForState, trackCtaRouted, dispatchCentralBranch } from "../lib/cta-routing";

export function UspPopup({ app, trigger, onClose }) {
  const lc = app.locale;
  const dialogRef = useRef(null);

  // Fire `usp_popup.shown` exactly once on mount. The trigger label
  // tells dashboards which arming path won the race.
  useEffect(() => {
    try {
      track("usp_popup.shown", { trigger, user_state: app.user?.plan ?? "anonymous" });
    } catch { /* never crash on telemetry */ }
    if (dialogRef.current) dialogRef.current.focus();
  }, [trigger, app.user]);

  // Centralized dismiss. Stamps the 7-day cap, fires telemetry,
  // calls onClose. Every exit path routes through here so the event
  // shape is uniform and the cap is never bypassed.
  const dismiss = (action) => {
    try {
      track("usp_popup.dismissed", { trigger, action });
    } catch { /* ignore */ }
    markUspPopupDismissed();
    onClose();
  };

  // Escape key dismiss + initial focus.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        dismiss("escape");
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]);

  const onBackdropClick = (e) => {
    if (e.target === e.currentTarget) dismiss("backdrop");
  };

  const onCtaClick = () => {
    try {
      track("usp_popup.cta_clicked", { trigger });
    } catch { /* ignore */ }
    // Route through Wave-1's utility — same branching as every other
    // generic upsell CTA. Paid users would have been excluded at the
    // trigger source, but the routing matrix is defensive.
    const branch = routeCtaForState("header_primary", app?.user);
    trackCtaRouted("header_primary", app?.user, branch, true);
    if (branch === "passthrough") {
      onClose();
      return;
    }
    // Don't await — dispatch may navigate; onClose() avoids the modal
    // sticking around if the dispatch fails silently.
    void dispatchCentralBranch(branch, app);
    onClose();
  };

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onClick={onBackdropClick}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={t("usp_popup.aria.dialog", lc)}
        className="modal usp-popup-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="modal-close"
          onClick={() => dismiss("close_button")}
          aria-label={t("usp_popup.aria.close", lc)}
        >
          <Icon name="close" size={18} />
        </button>

        <div className="usp-popup-head">
          <PulpoLogo size={20} />
          <span className="hp-usp-eyebrow">
            <IconLock size={14} strokeWidth={1.8} className="hp-usp-eyebrow-icon" />
            {t("home.usp.eyebrow", lc)}
          </span>
          <h2 className="hp-usp-h2">{t("home.usp.h2", lc)}</h2>
        </div>

        <div className="usp-popup-cards">
          <article className="hp-usp-card">
            <IconMailFast size={24} strokeWidth={1.5} className="hp-usp-card-icon" />
            <h3 className="hp-usp-card-title">{t("home.usp.card1.title", lc)}</h3>
            <p className="hp-usp-card-body">{t("home.usp.card1.body", lc)}</p>
          </article>
          <article className="hp-usp-card">
            <IconListSearch size={24} strokeWidth={1.5} className="hp-usp-card-icon" />
            <h3 className="hp-usp-card-title">{t("home.usp.card2.title", lc)}</h3>
            <p className="hp-usp-card-body">{t("home.usp.card2.body", lc)}</p>
          </article>
          <article className="hp-usp-card">
            <IconMapPinHeart size={24} strokeWidth={1.5} className="hp-usp-card-icon" />
            <h3 className="hp-usp-card-title">{t("home.usp.card3.title", lc)}</h3>
            <p className="hp-usp-card-body">{t("home.usp.card3.body", lc)}</p>
          </article>
        </div>

        <div className="usp-popup-actions">
          <button
            type="button"
            className="btn-primary lg"
            onClick={onCtaClick}
          >
            {t("usp_popup.cta_primary", lc)}
          </button>
          <button
            type="button"
            className="link-btn"
            onClick={() => dismiss("maybe_later")}
          >
            {t("usp_popup.cta_dismiss", lc)}
          </button>
        </div>
      </div>
    </div>
  );
}
