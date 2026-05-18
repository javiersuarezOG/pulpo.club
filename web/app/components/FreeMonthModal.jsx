// Free-month conversion modal. Opens from hero CTA, USP section, and
// listing-card clicks for anon + free users (paid users never see it).
// Replaces the previous "redirect to /start?intent=upgrade" page jump
// with an in-page modal that POSTs to /api/stripe/start-checkout.
//
// Mechanics modeled on ProUpsellModal (pages.jsx) — backdrop + dialog
// with focus management, Escape/backdrop/close-button/Maybe-later
// dismiss paths, all routed through the same `dismiss(action)` helper
// so the telemetry shape stays uniform.
//
// Content scope (verbatim per the brief): one headline, one body line,
// three bullets, one primary CTA, one secondary dismiss. No
// icon-in-circle cards (USPBand owns that pattern; the modal must look
// distinct to avoid duplicating the visual language).

import React, { useEffect, useRef, useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { Icon } from "../components.jsx";
import { priceForCountry, fetchPriceForCurrentGeo } from "../lib/pricing";
import { useCampaignParams } from "../lib/campaign";
import { startCheckoutFromModal } from "../lib/stripe-modal-checkout";

/**
 * @param {object} props
 * @param {object} props.app    — App state (locale, user, etc.).
 * @param {string} props.trigger — One of the FreeMonthModalTrigger values
 *                                (see lib/cta-routing.ts). Drives the
 *                                trigger property on every telemetry event.
 * @param {() => void} props.onClose — App-level setter to unmount the modal.
 */
export function FreeMonthModal({ app, trigger, onClose }) {
  const lc = app.locale;
  const dialogRef = useRef(null);

  // Campaign params (?code= + utm_* + ?cancelled=1) come from the same
  // hook /start and ProUpsellModal use. Without this, a Reddit promo
  // visitor who clicked through the hero CTA after dismissing the
  // auto-mount ProUpsellModal would lose their pre-applied discount.
  const { urlCode, utms } = useCampaignParams();

  // Geo-derived display price. Starts with USD fallback (synchronous so
  // the modal renders immediately with a real price); refines via the
  // module-level cache in pricing.ts on first /api/geo round trip.
  const [price, setPrice] = useState(() => priceForCountry(null));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // ── Mount telemetry + geo refine ────────────────────────────────────
  useEffect(() => {
    try {
      track("free_month_modal.shown", {
        trigger,
        user_state: app.user?.plan === "free" ? "free" : "anonymous",
        // Paid users don't reach this modal — the routing matrix returns
        // passthrough. But the schema is open-string'd to anon/free only
        // for safety.
        flag_enabled: true,
        has_code: !!urlCode,
        geo_currency: price.currency,
        price_amount: price.amount,
      });
    } catch { /* never crash on telemetry */ }

    let cancelled = false;
    fetchPriceForCurrentGeo().then((p) => {
      if (!cancelled) setPrice(p);
    });

    if (dialogRef.current) dialogRef.current.focus();
    return () => { cancelled = true; };
    // Mount-only. We intentionally don't re-fire `shown` on price change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]);

  // ── Dismiss helpers ─────────────────────────────────────────────────
  // Central dismiss. Every exit path routes through here so the event
  // shape is uniform.
  const dismiss = (action) => {
    try { track("free_month_modal.dismissed", { trigger, action }); } catch { /* ignore */ }
    onClose();
  };

  // Escape key dismiss.
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

  // ── CTA submit ──────────────────────────────────────────────────────
  const onCtaClick = async () => {
    setError(null);
    try { track("free_month_modal.cta_clicked", { trigger, has_code: !!urlCode }); } catch { /* ignore */ }
    setSubmitting(true);

    const result = await startCheckoutFromModal({
      locale: lc,
      utms,
      urlCode,
    });

    if (result.kind === "redirect") {
      try {
        track("free_month_modal.checkout_redirected", { trigger, has_code: !!urlCode });
      } catch { /* ignore */ }
      window.location.assign(result.url);
      return;
    }

    // Both rate_limited and error surface the same user-facing message
    // (the distinction matters for telemetry, not for the visitor).
    try {
      track("free_month_modal.error", {
        trigger,
        reason: result.kind === "rate_limited" ? "rate_limited" : result.reason,
      });
    } catch { /* ignore */ }
    setError(t("free_month_modal.error", lc));
    setSubmitting(false);
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
        aria-label={t("free_month_modal.aria.dialog", lc)}
        className="modal free-month-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="modal-close"
          onClick={() => dismiss("close_button")}
          aria-label={t("free_month_modal.aria.close", lc)}
        >
          <Icon name="close" size={18} />
        </button>

        <h2 className="free-month-modal-headline">{t("free_month_modal.headline", lc)}</h2>
        <p className="free-month-modal-body">{t("free_month_modal.body", lc)}</p>

        <ul className="free-month-modal-bullets">
          <li><span className="free-month-modal-bullet-mark" aria-hidden="true">✓</span> {t("free_month_modal.bullet.1", lc)}</li>
          <li><span className="free-month-modal-bullet-mark" aria-hidden="true">✓</span> {t("free_month_modal.bullet.2", lc)}</li>
          <li><span className="free-month-modal-bullet-mark" aria-hidden="true">✓</span> {t("free_month_modal.bullet.3", lc)}</li>
        </ul>

        <button
          type="button"
          className="btn-primary lg free-month-modal-cta-primary"
          onClick={onCtaClick}
          disabled={submitting}
        >
          {submitting
            ? t("free_month_modal.cta_primary_submitting", lc)
            : t("free_month_modal.cta_primary", lc, { price: price.displayString })}
        </button>

        {urlCode && (
          <p className="free-month-modal-code-note" aria-live="polite">
            {t("free_month_modal.code_applied_note", lc)}
          </p>
        )}

        {error && (
          <p className="free-month-modal-error" role="alert">{error}</p>
        )}

        <button
          type="button"
          className="link-btn free-month-modal-cta-dismiss"
          onClick={() => dismiss("maybe_later")}
        >
          {t("free_month_modal.cta_dismiss", lc)}
        </button>
      </div>
    </div>
  );
}
