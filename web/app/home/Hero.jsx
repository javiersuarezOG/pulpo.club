// Rewritten homepage hero — copy-led, email-form-anchored.
//
// Replaces the rotating-listing hero (legacy hero in pages.jsx). The
// brief's design: small green pill eyebrow, H1, tagline, email input +
// "Get the 10 best" button, sub-text. Mobile-first: input + button
// stack vertically on small screens, side-by-side from 768px.
//
// Email submit POSTs to /api/newsletter (wired in Phase 6 via Resend).
// Until that endpoint lands, the fetch fails with 404 and we render
// the generic error toast. The track() call still fires so PostHog
// shows submit-rate trends regardless of backend state.
//
// PII (rewrite plan §10e): NEVER send the raw email to telemetry —
// only the domain after @. Server-side never logs the address either
// (api/newsletter.js to follow the same rule).
import React, { useState } from "react";
import { t } from "../i18n.jsx";
import { track } from "../telemetry/hook";

// Loose email regex — accepts most well-formed addresses, rejects
// obvious garbage. Server is the final validator (Resend itself does
// stricter checks); this gate is for fast client-side feedback so the
// user doesn't wait on a network round-trip for an obvious typo.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function emailDomain(email) {
  const at = email.lastIndexOf("@");
  if (at < 0) return "";
  return email.slice(at + 1).toLowerCase();
}

/**
 * @param {object} props
 * @param {string} props.locale         — "en" | "es"
 */
export function Hero({ locale }) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle");   // idle | submitting | success | error
  const [errorKey, setErrorKey] = useState(null); // i18n key for the error message

  const onSubmit = async (e) => {
    e.preventDefault();
    if (status === "submitting") return;

    const trimmed = email.trim();
    if (!EMAIL_RE.test(trimmed)) {
      setStatus("error");
      setErrorKey("new_hero.error_invalid_email");
      track("hero.email_submitted", {
        source: "homepage_hero",
        email_domain_only: emailDomain(trimmed) || "unknown",
        result: "validation_failed",
      });
      return;
    }

    setStatus("submitting");
    setErrorKey(null);

    let response = null;
    try {
      response = await fetch("/api/newsletter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmed, source: "homepage_hero" }),
      });
    } catch {
      // Network error — surface generic copy, fire the same telemetry
      // as a 5xx so funnel doesn't undercount errors.
      track("hero.email_submitted", {
        source: "homepage_hero",
        email_domain_only: emailDomain(trimmed),
        result: "error",
      });
      setStatus("error");
      setErrorKey("new_hero.error_generic");
      return;
    }

    if (response.ok) {
      track("hero.email_submitted", {
        source: "homepage_hero",
        email_domain_only: emailDomain(trimmed),
        result: "success",
      });
      setStatus("success");
      setEmail("");
      return;
    }

    // Non-2xx — parse the response body when possible so we can map
    // server-defined reasons to specific copy. The Resend integration
    // in Phase 6 will return { error: "already_subscribed" | "rate_limited" | ... }.
    let body = null;
    try {
      body = await response.json();
    } catch {
      // ignore — body parse failure falls through to generic error
    }
    const reason = body && typeof body.error === "string" ? body.error : null;

    let outcome = "error";
    let key = "new_hero.error_generic";
    if (response.status === 429 || reason === "rate_limited") {
      outcome = "rate_limited";
      key = "new_hero.error_generic"; // no dedicated copy yet — generic is fine
    } else if (reason === "already_subscribed") {
      outcome = "already_subscribed";
      key = "new_hero.error_already";
    } else if (response.status === 400 || reason === "invalid_email") {
      outcome = "validation_failed";
      key = "new_hero.error_invalid_email";
    }

    track("hero.email_submitted", {
      source: "homepage_hero",
      email_domain_only: emailDomain(trimmed),
      result: outcome,
    });
    setStatus(outcome === "already_subscribed" ? "success" : "error");
    setErrorKey(key);
  };

  return (
    <section className="new-hero" aria-labelledby="new-hero-headline">
      <div className="new-hero-inner">
        <span className="new-hero-eyebrow">{t("new_hero.eyebrow", locale)}</span>
        <h1 id="new-hero-headline" className="new-hero-headline">
          {t("new_hero.headline", locale)}
        </h1>
        <p className="new-hero-tagline">{t("new_hero.tagline", locale)}</p>

        <form className="new-hero-form" onSubmit={onSubmit} noValidate>
          <label className="new-hero-form-label" htmlFor="new-hero-email">
            {/* Visually-hidden label for screen readers — the
                placeholder is decorative, not a label. */}
            <span className="sr-only">{t("new_hero.email_placeholder", locale)}</span>
          </label>
          <input
            id="new-hero-email"
            className="new-hero-email"
            type="email"
            autoComplete="email"
            inputMode="email"
            placeholder={t("new_hero.email_placeholder", locale)}
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              if (status === "error") {
                setStatus("idle");
                setErrorKey(null);
              }
            }}
            disabled={status === "submitting" || status === "success"}
            aria-invalid={status === "error"}
            aria-describedby={errorKey ? "new-hero-error" : undefined}
          />
          <button
            type="submit"
            className="new-hero-submit"
            disabled={status === "submitting" || status === "success"}
            aria-busy={status === "submitting" || undefined}
          >
            {status === "submitting"
              ? t("new_hero.cta_loading", locale)
              : t("new_hero.cta", locale)}
          </button>
        </form>

        {status === "success" ? (
          <p className="new-hero-status new-hero-status-success" role="status">
            {t("new_hero.success", locale)}
          </p>
        ) : errorKey ? (
          <p id="new-hero-error" className="new-hero-status new-hero-status-error" role="alert">
            {t(errorKey, locale)}
          </p>
        ) : (
          <p className="new-hero-sub">{t("new_hero.sub", locale)}</p>
        )}
      </div>
    </section>
  );
}
