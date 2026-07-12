import React from "react";
import { t } from "../i18n.jsx";
import "./SubscribeConfirm.css";

// Shared "you're already on the list" confirmation — treatment B from the
// design mockup (the form dissolves, this rises in its place): a sage check
// badge, a serif headline, one warm line. Rendered by EVERY signup route
// (AccessBlock hero + access modals, the legacy HeroV5 EmailCapture, and
// EmailCaptureModal) so a returning member sees the exact same moment
// everywhere. Returning members ONLY — a brand-new join still gets the full
// JoinCelebration octopus, so this never competes with it.
//
// `compact` centers it for the narrow modal body; default is left-aligned to
// match the hero form.
export function SubscribeConfirm({ locale, compact = false }) {
  return (
    <div
      className={`subscribe-confirm${compact ? " is-compact" : ""}`}
      role="status"
      aria-live="polite"
    >
      <div className="subscribe-confirm-badge" aria-hidden="true">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
          <path
            className="subscribe-confirm-check"
            d="M5 12.5l4.2 4.2L19 7.3"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <h3 className="subscribe-confirm-title">{t("subscribe.already.title", locale)}</h3>
      <p className="subscribe-confirm-body">{t("subscribe.already.body", locale)}</p>
    </div>
  );
}
