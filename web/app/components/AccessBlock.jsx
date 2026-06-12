// AccessBlock — the reusable "3 ways in" surface (identical everywhere it
// renders: home hero + every access modal). It reads the enabled, ordered
// options for its `surface` from config/access.ts and renders each. Every
// option's action is self-contained and decoupled:
//   ① free_email → subscribeEmail (Resend) + becomeFreeMember
//   ② go_pro     → startCheckoutFromModal (Stripe)
//   ③ sign_in    → Clerk openSignIn
// Nothing here couples the options to each other, and nothing downstream
// keys off which was used — only off the resulting state.

import React, { useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";
import { subscribeEmail, NL_EMAIL_RE } from "../lib/newsletter-signup";
import { startCheckoutFromModal } from "../lib/stripe-modal-checkout";
import { accessOptionsFor } from "../config/access";

/**
 * @param {object} props
 * @param {object} props.app
 * @param {string} props.locale
 * @param {import("../config/access").AccessSurface} props.surface
 * @param {{reason?: string, listingId?: string|null}} [props.cfg] — context (top-3 to open after join)
 * @param {() => void} [props.onDone] — called after a successful action (e.g. close the modal)
 */
export function AccessBlock({ app, locale: lc, surface, cfg, onDone }) {
  const options = accessOptionsFor(surface);
  const reason = (cfg && cfg.reason) || surface;
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle"); // idle | loading | invalid | error

  // ① Join free — email → Resend + Free membership (+ open the stashed top-3).
  const onJoinFree = async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const value = email.trim();
    if (!NL_EMAIL_RE.test(value)) { setStatus("invalid"); return; }
    setStatus("loading");
    const domain = value.split("@")[1] || "";
    const result = await subscribeEmail(value, { source: `access_${surface}`, locale: lc });
    try { track("access.free_submitted", { surface, reason, email_domain_only: domain, result: result.kind }); } catch { /* ignore */ }
    if (result.kind === "success" || result.kind === "already") {
      try { track("free_member_created", { surface, reason, via: "access_block" }); } catch { /* ignore */ }
      app.becomeFreeMember({ email: value, openListingId: reason === "top3" ? (cfg && cfg.listingId) || null : null });
      if (typeof onDone === "function") onDone();
      return;
    }
    setStatus(result.kind === "invalid" ? "invalid" : "error");
  };

  // ② Go Pro — straight to Stripe checkout (first month free pre-applied).
  const onGoPro = async () => {
    try { track("access.go_pro_clicked", { surface, reason }); } catch { /* ignore */ }
    const result = await startCheckoutFromModal({
      locale: lc,
      urlCode: "PULPOFREEMONTH",
      cancelPath: typeof window !== "undefined" ? window.location.pathname + window.location.search : null,
    });
    if (result && result.kind === "redirect") { window.location.assign(result.url); return; }
    setStatus("error");
  };

  // ③ Sign in — existing Pro member (Clerk). Falls back to the legacy login modal.
  const onSignIn = () => {
    try { track("access.sign_in_clicked", { surface, reason }); } catch { /* ignore */ }
    if (typeof onDone === "function") onDone();
    if (app.clerkActions && typeof app.clerkActions.openSignIn === "function") app.clerkActions.openSignIn({});
    else if (typeof app.openSignup === "function") app.openSignup({ mode: "login" });
  };

  // Render each enabled option in its configured order. `first` controls the
  // "or" dividers so they only appear between options, regardless of subset.
  const rows = [];
  options.forEach((id, i) => {
    if (i > 0 && (id === "go_pro" || (id === "free_email"))) {
      rows.push(<div className="access-or" key={`or-${id}`}>{t("access.or", lc)}</div>);
    }
    if (id === "free_email") {
      rows.push(
        <form className="access-free" key="free" onSubmit={onJoinFree} noValidate>
          <input
            type="email"
            className="access-input"
            placeholder={t("access.email.placeholder", lc)}
            aria-label={t("access.email.aria", lc)}
            value={email}
            onChange={(e) => { setEmail(e.target.value); if (status === "invalid" || status === "error") setStatus("idle"); }}
            disabled={status === "loading"}
          />
          <button type="submit" className="btn-primary lg block access-cta-free" disabled={status === "loading"}>
            {t(status === "loading" ? "access.free.cta_loading" : "access.free.cta", lc)}
          </button>
          <div className="access-free-note">{t("access.free.note", lc)}</div>
          {(status === "invalid" || status === "error") && (
            <p className="access-error" role="alert">
              {t(status === "invalid" ? "access.error.invalid" : "access.error.generic", lc)}
            </p>
          )}
        </form>,
      );
    } else if (id === "go_pro") {
      rows.push(
        <div className="access-pro" key="pro">
          <button type="button" className="btn-pro lg block access-cta-pro" onClick={onGoPro}>
            {t("access.go_pro.cta", lc)}
          </button>
          <div className="access-pro-sub">{t("access.go_pro.sub", lc)}</div>
        </div>,
      );
    } else if (id === "sign_in") {
      rows.push(
        <div className="access-signin" key="signin">
          {t("access.signin.prefix", lc)}{" "}
          <button type="button" className="access-signin-link" onClick={onSignIn}>{t("access.signin.link", lc)}</button>
        </div>,
      );
    }
  });

  return <div className="access-block">{rows}</div>;
}
