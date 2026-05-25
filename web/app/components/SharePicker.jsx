// SharePicker — Airbnb-style share modal opened from the Compartir
// button. Single picker handles mobile + desktop (bottom-sheet at
// ≤600px via the shared .modal media query, centered 560px above).
//
// Six channels: WhatsApp, Messages, Copy link, Email, Facebook, TikTok.
// Same options for free + Pro — sharing is a top-of-funnel growth
// surface, not a paywall.
//
// Source-opacity contract (see CLAUDE.md): no field rendered here or
// in the pre-filled caption ever reveals the broker. URL is
// `pulpo.club/l/<token>` via shareUrlFor(); title/hook come from
// derived/i18n strings, never `listing.source_label`. PR #2 adds the
// crawler-aware OG card at the same URL.
import React, { useEffect, useRef } from "react";
import { t, tr, formatPriceI18n } from "../i18n.jsx";
import { Icon, PulpoMark } from "../components.jsx";
import { track } from "../telemetry/hook";
import { shareUrlFor } from "../lib/share.ts";

// Pick the one-line hook printed under the title in the WhatsApp
// pre-fill. Priority: walk-to-beach > short drive > lake > generic.
// Reads only derived/normalized fields — no source-bearing copy.
function captionHook(listing, lc) {
  const km = listing.dist_beach_km;
  if (listing.is_walk_to_beach && typeof km === "number" && km < 1) {
    // Walking pace ~5km/h → minutes = km * 12. Round to 5-min steps so
    // the copy reads "5 / 10 / 15 min" instead of "7 min".
    const minutes = Math.max(5, Math.round((km * 12) / 5) * 5);
    return t("share.hook.beach_walk", lc, { minutes });
  }
  if (typeof km === "number" && km > 0 && km < 5) {
    return t("share.hook.beach_drive", lc, { km: Math.round(km) });
  }
  if (listing.is_on_lake) return t("share.hook.lake", lc);
  return t("share.hook.generic", lc);
}

function buildCaption(listing, lc) {
  const title = tr(listing.title, lc) || t("share.hook.generic", lc);
  const priceStr = listing.price != null
    ? formatPriceI18n(listing.price, lc)
    : null;
  const titleLine = priceStr ? `${title} — ${priceStr}` : title;
  return `${titleLine}\n${captionHook(listing, lc)}`;
}

// Channel-specific outbound URLs. Each receives the listing's
// /l/<token> share URL plus the pre-filled caption, and returns a
// destination URL the picker opens via window.open / location.assign.
const CHANNELS = {
  whatsapp: (url, caption) =>
    `https://wa.me/?text=${encodeURIComponent(`${caption}\n${url}`)}`,
  // sms: body= works on iOS 14+; the ?&body= form is required on some
  // older Androids but iOS accepts both. Single `?` is the modern form.
  sms: (url, caption) =>
    `sms:?body=${encodeURIComponent(`${caption}\n${url}`)}`,
  email: (url, caption, subject) =>
    `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(`${caption}\n\n${url}`)}`,
  facebook: (url) =>
    `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`,
};

export default function SharePicker({ listing, app, onClose }) {
  const lc = app.locale;
  const dialogRef = useRef(null);
  const shareUrl = shareUrlFor(listing.id);
  const caption = buildCaption(listing, lc);
  const emailSubject = t("share.email.subject", lc, { title: tr(listing.title, lc) });

  // Telemetry on mount: paired with share.channel_clicked below so the
  // funnel (opened → clicked) is queryable in PostHog.
  useEffect(() => {
    try { track("share.opened", { listing_id: listing.id }); } catch { /* noop */ }
  }, [listing.id]);

  // Focus the dialog on mount + esc-to-close. Mirrors FreeMonthModal.
  useEffect(() => {
    dialogRef.current?.focus();
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onBackdropClick = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  const fireChannel = (channel, fn) => {
    try { track("share.channel_clicked", { listing_id: listing.id, channel }); } catch { /* noop */ }
    fn();
    onClose();
  };

  const openInNew = (url) => {
    // noopener prevents the target from accessing window.opener; popup
    // blockers allow this in synchronous click handlers.
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const onCopy = () => fireChannel("copy", async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      app.showToast(t("share.toast.copied", lc));
    } catch {
      // Older Safari without secure-context clipboard — fall back to a
      // hidden textarea + execCommand. Not ideal but better than failing
      // silently. Modern devices never hit this branch.
      const ta = document.createElement("textarea");
      ta.value = shareUrl;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); app.showToast(t("share.toast.copied", lc)); } catch { /* swallow */ }
      document.body.removeChild(ta);
    }
  });

  const onTikTok = () => fireChannel("tiktok", async () => {
    // TikTok has no public web→TikTok share API. Universal pattern:
    // copy link, send the user to TikTok upload, show a toast with the
    // "paste in TikTok" instruction.
    try { await navigator.clipboard.writeText(shareUrl); } catch { /* swallow */ }
    app.showToast(t("share.toast.tiktok", lc));
    openInNew("https://www.tiktok.com/upload");
  });

  // The 6 options in render order. WhatsApp first (Salvadoran share
  // channel of record), TikTok last (newest + needs the toast).
  const options = [
    {
      key: "whatsapp",
      label: t("share.channel.whatsapp", lc),
      featured: true,
      tone: "wa",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="#fff" aria-hidden="true">
          <path d="M17.5 14.4c-.3-.1-1.7-.8-2-.9-.3-.1-.5-.1-.7.1-.2.3-.7.9-.9 1.1-.2.2-.3.2-.6.1-.3-.1-1.2-.4-2.3-1.4-.9-.8-1.4-1.7-1.6-2-.2-.3 0-.5.1-.6.1-.1.3-.3.4-.5.1-.2.2-.3.3-.5.1-.2 0-.4 0-.5 0-.1-.7-1.6-.9-2.2-.2-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.7.4-.3.3-1 .9-1 2.2 0 1.3.9 2.6 1.1 2.8.1.2 1.9 2.9 4.7 4 .7.3 1.2.5 1.6.6.7.2 1.3.2 1.8.1.5-.1 1.7-.7 2-1.4.2-.7.2-1.3.2-1.4-.1-.1-.3-.2-.6-.3zM12 2C6.5 2 2 6.5 2 12c0 1.7.5 3.4 1.3 4.8L2 22l5.4-1.3c1.4.7 3 1.1 4.6 1.1 5.5 0 10-4.5 10-10S17.5 2 12 2z"/>
        </svg>
      ),
      onClick: () => fireChannel("whatsapp", () => openInNew(CHANNELS.whatsapp(shareUrl, caption))),
    },
    {
      key: "sms",
      label: t("share.channel.sms", lc),
      tone: "sms",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="#fff" aria-hidden="true">
          <path d="M12 3C6.48 3 2 6.92 2 11.5c0 2.45 1.27 4.65 3.3 6.15v3.85l3.7-2.1c.95.2 1.95.3 3 .3 5.52 0 10-3.92 10-8.5S17.52 3 12 3z"/>
        </svg>
      ),
      // location.assign for sms: — window.open with sms: is flaky on iOS
      // (gets blocked by the popup heuristic). Direct nav works cleanly.
      onClick: () => fireChannel("sms", () => { window.location.assign(CHANNELS.sms(shareUrl, caption)); }),
    },
    {
      key: "copy",
      label: t("share.channel.copy", lc),
      tone: "copy",
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
        </svg>
      ),
      onClick: onCopy,
    },
    {
      key: "email",
      label: t("share.channel.email", lc),
      tone: "email",
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" aria-hidden="true">
          <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
          <polyline points="22,6 12,13 2,6"/>
        </svg>
      ),
      onClick: () => fireChannel("email", () => { window.location.assign(CHANNELS.email(shareUrl, caption, emailSubject)); }),
    },
    {
      key: "facebook",
      label: t("share.channel.facebook", lc),
      tone: "fb",
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="#fff" aria-hidden="true">
          <path d="M22 12a10 10 0 1 0-11.56 9.88v-6.99H7.9V12h2.54V9.8c0-2.51 1.5-3.9 3.78-3.9 1.1 0 2.24.2 2.24.2v2.46h-1.26c-1.24 0-1.63.77-1.63 1.56V12h2.77l-.44 2.89h-2.33v6.99A10 10 0 0 0 22 12z"/>
        </svg>
      ),
      onClick: () => fireChannel("facebook", () => openInNew(CHANNELS.facebook(shareUrl))),
    },
    {
      key: "tiktok",
      label: t("share.channel.tiktok", lc),
      tone: "tt",
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="#fff" aria-hidden="true">
          <path d="M19.6 7.3a4.8 4.8 0 0 1-2.9-1.05A4.8 4.8 0 0 1 15.1 3h-3.4v12.6c0 1.55-1.25 2.8-2.8 2.8a2.8 2.8 0 1 1 0-5.6c.28 0 .55.04.8.12V9.45a6.2 6.2 0 0 0-.8-.05 6.2 6.2 0 1 0 6.2 6.2V9.4a8.1 8.1 0 0 0 4.7 1.5V7.3z"/>
        </svg>
      ),
      onClick: onTikTok,
    },
  ];

  const titleStr = tr(listing.title, lc) || "";
  const heroPhoto = Array.isArray(listing.photos) ? listing.photos[0] : null;
  const priceStr = listing.price != null ? formatPriceI18n(listing.price, lc) : null;

  return (
    <div className="modal-backdrop" role="presentation" onClick={onBackdropClick}>
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={t("share.aria.dialog", lc)}
        className="modal share-picker"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="modal-close"
          onClick={onClose}
          aria-label={t("share.aria.close", lc)}
        >
          <Icon name="close" size={18} />
        </button>

        <div className="share-picker-brand">
          <PulpoMark size={22} />
          <span className="share-picker-wordmark">pulpo</span>
        </div>

        <h2 className="share-picker-title">{t("share.modal.title", lc)}</h2>

        <div className="share-picker-listing">
          {heroPhoto && (
            <img className="share-picker-thumb" src={heroPhoto} alt="" aria-hidden="true" />
          )}
          <div className="share-picker-meta">
            <div className="share-picker-listing-title">
              {titleStr}{priceStr ? ` — ${priceStr}` : ""}
            </div>
            <div className="share-picker-listing-sub">{captionHook(listing, lc)}</div>
          </div>
        </div>

        <div className="share-opts">
          {options.map((opt) => (
            <button
              key={opt.key}
              type="button"
              className={`share-opt${opt.featured ? " is-featured" : ""}`}
              onClick={opt.onClick}
            >
              <span className={`share-opt-ico share-opt-${opt.tone}`}>{opt.icon}</span>
              <span className="share-opt-label">{opt.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
