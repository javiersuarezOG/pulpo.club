// /start — public marketing landing for the acquisition funnel.
//
// Self-contained — no TopNav / BottomNav / footer from the main app shell.
// Mount-time branch in app.jsx picks this up before <App /> runs so the
// page is a hard navigation away from the SPA, faster TTI on mobile.
//
// Flow:
//   email (+ optional promo code) → POST /api/stripe/start-checkout
//                                 → window.location.assign(stripeUrl)
//                                 → user pays on Stripe-hosted page
//                                 → returns to /welcome (anonymous flow)
//                                   or / with ?upgrade=success (signed-in)
//
// `?code=<X>` pre-fills the code input and visually demotes the paid card.
// `?utm_*` params get attached to the Stripe session metadata + replayed
// on the webhook into the Clerk user's `privateMetadata.acquisitionUtms`.

import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { t, useLocale } from "./i18n.jsx";
import { PulpoLogo } from "./components.jsx";
import { track } from "./telemetry/hook";
import { priceForCountry, fetchPriceForCurrentGeo } from "./lib/pricing";
import "./styles/start.css";

// Total catalog size — surfaced in the trust strip. Hardcoded for v1
// rather than fetching /data/ranked.json on a marketing page (extra ~1MB
// payload for one number). Refresh occasionally by hand or wire a tiny
// /api/catalog-count endpoint in a follow-up.
const CATALOG_COUNT = 900;

// Listing photo to show in the hero — picked at build time. Falls back
// to a CSS gradient if missing. The matching file lives in
// web/photos/ and is referenced via the public /photos/:file rewrite.
// Pick a hero file that has high photoscount + scenic value.
const HERO_PHOTO_URL = "/photos/bienesraices_1014.jpg";

function readQueryParam(name) {
  if (typeof window === "undefined") return null;
  try {
    return new URLSearchParams(window.location.search).get(name);
  } catch { return null; }
}

const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];

function captureUtms() {
  if (typeof window === "undefined") return {};
  try {
    const params = new URLSearchParams(window.location.search);
    const out = {};
    for (const k of UTM_KEYS) {
      const v = params.get(k);
      if (v) {
        out[k] = v;
        // Persist across the Stripe redirect — primarily for the welcome
        // page or any subsequent attribution use. PostHog also captures
        // these on $pageview, this is belt-and-braces.
        try { sessionStorage.setItem(`pulpo-${k}`, v); } catch {}
      } else {
        try {
          const cached = sessionStorage.getItem(`pulpo-${k}`);
          if (cached) out[k] = cached;
        } catch {}
      }
    }
    return out;
  } catch { return {}; }
}

export default function StartPage() {
  const [locale, setLocale] = useLocale();
  const lc = locale;

  // Code-mode is determined by URL on initial render and locked there.
  // If the user types into the code field manually, we still keep the
  // card layout stable — the visual switch is a one-way URL-driven thing
  // so the page doesn't reshuffle as the user types.
  const initialCode = useMemo(() => {
    const c = readQueryParam("code");
    return c ? c.trim().toUpperCase() : "";
  }, []);
  const initialCancelled = useMemo(() => readQueryParam("cancelled") === "1", []);

  const [email, setEmail] = useState("");
  const [promoCode, setPromoCode] = useState(initialCode);
  const [submitting, setSubmitting] = useState(false);
  // { card: "paid" | "code", message: string } | null
  const [error, setError] = useState(null);
  // Geo-derived price; starts at default USD and resolves on mount.
  const [price, setPrice] = useState(() => priceForCountry(null));
  // Sticky CTA visible after hero scrolls out (mobile).
  const [stickyVisible, setStickyVisible] = useState(false);
  const heroSentinelRef = useRef(null);

  const codeMode = initialCode.length > 0;
  const utms = useMemo(() => captureUtms(), []);

  useEffect(() => {
    track("start.viewed", { has_code: codeMode });
  }, [codeMode]);

  useEffect(() => {
    let cancelled = false;
    fetchPriceForCurrentGeo().then((p) => {
      if (!cancelled) setPrice(p);
    });
    return () => { cancelled = true; };
  }, []);

  // Mobile sticky CTA — show after the hero CTA is out of view. Use an
  // IntersectionObserver on a sentinel placed at the bottom of the hero
  // so the bar appears once the user has scrolled past the value-prop
  // section, not when they first land.
  useEffect(() => {
    const el = heroSentinelRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const e = entries[0];
        if (!e) return;
        setStickyVisible(!e.isIntersecting);
      },
      { rootMargin: "0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const handleSubmit = useCallback(
    async (mode) => {
      setError(null);
      const trimmedEmail = email.trim().toLowerCase();
      const trimmedCode = promoCode.trim().toUpperCase();

      if (!trimmedEmail) {
        setError({ card: mode, message: t("start.error.generic", lc) });
        return;
      }

      const codePrefilled = mode === "code" && initialCode === trimmedCode && trimmedCode.length > 0;
      track("start.cta_clicked", {
        type: mode,
        email_entered: trimmedEmail.length > 0,
        code_prefilled: codePrefilled,
      });

      setSubmitting(true);
      try {
        const res = await fetch("/api/stripe/start-checkout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: trimmedEmail,
            promoCode: mode === "code" ? trimmedCode : null,
            locale: lc,
            ...utms,
          }),
        });

        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          const reason = detail && detail.error;
          if (reason === "invalid_promo_code") {
            track("start.code_error_shown", { reason: "invalid_promo_code" });
            setError({ card: "code", message: t("start.join.code.error_invalid", lc) });
          } else if (reason === "rate_limited") {
            setError({ card: mode, message: t("start.error.rate_limited", lc) });
          } else if (reason === "invalid_email") {
            setError({ card: mode, message: t("start.error.generic", lc) });
          } else {
            track("api.error", {
              endpoint: "/api/stripe/start-checkout",
              status: res.status,
              reason: reason,
              detail: detail && detail.detail,
            });
            setError({ card: mode, message: t("start.error.generic", lc) });
          }
          setSubmitting(false);
          return;
        }

        const data = await res.json();
        if (!data || !data.url) {
          setError({ card: mode, message: t("start.error.generic", lc) });
          setSubmitting(false);
          return;
        }
        track("start.checkout_redirected", {
          type: mode,
          had_promo_code: mode === "code" && trimmedCode.length > 0,
        });
        window.location.assign(data.url);
      } catch (err) {
        track("api.error", {
          endpoint: "/api/stripe/start-checkout",
          status: 0,
          reason: "network",
          detail: err && err.message,
        });
        setError({ card: mode, message: t("start.error.generic", lc) });
        setSubmitting(false);
      }
    },
    [email, promoCode, lc, utms, initialCode]
  );

  const scrollToJoin = useCallback(() => {
    const el = document.getElementById("join");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <div className="start-page" data-mode={codeMode ? "code" : "paid"}>
      <header className="start-nav">
        <a href="/" className="start-logo" aria-label="Pulpo home">
          <PulpoLogo size={28} />
        </a>
        <a href="/" className="start-nav-link">{t("start.nav.login_link", lc)}</a>
      </header>

      <section className="start-hero">
        <div className="start-hero-text">
          <div className="start-hero-eyebrow">{t("start.hero.eyebrow", lc)}</div>
          <h1 className="start-hero-h1">{t("start.hero.h1", lc)}</h1>
          <p className="start-hero-sub">{t("start.hero.sub", lc)}</p>
          <div className="start-hero-ctas">
            <button
              type="button"
              className="start-cta-primary"
              onClick={scrollToJoin}
            >
              {t("start.hero.cta_primary", lc, { price: price.displayString })}
            </button>
            <button
              type="button"
              className="start-cta-secondary"
              onClick={scrollToJoin}
            >
              {t("start.hero.cta_secondary", lc)}
            </button>
          </div>
          <p className="start-hero-trust">{t("start.hero.trust_micro", lc)}</p>
        </div>
        <div
          className="start-hero-visual"
          style={{ backgroundImage: `url(${HERO_PHOTO_URL})` }}
          aria-hidden="true"
        />
      </section>

      {initialCancelled && (
        <div className="start-cancelled-banner" role="status">
          {t("start.cancelled_notice", lc)}
        </div>
      )}

      <div ref={heroSentinelRef} className="start-hero-sentinel" aria-hidden="true" />

      <section className="start-value">
        <article className="start-value-block start-value-block-large">
          <h2 className="start-value-label">{t("start.value.a.label", lc)}</h2>
          <p className="start-value-body">{t("start.value.a.body", lc)}</p>
        </article>
        <div className="start-value-stack">
          <article className="start-value-block">
            <h2 className="start-value-label">{t("start.value.b.label", lc)}</h2>
            <p className="start-value-body">{t("start.value.b.body", lc)}</p>
          </article>
          <article className="start-value-block">
            <h2 className="start-value-label">{t("start.value.c.label", lc)}</h2>
            <p className="start-value-body">{t("start.value.c.body", lc)}</p>
          </article>
        </div>
      </section>

      <section className="start-trust" aria-label="Social proof">
        <p className="start-trust-stat">
          {t("start.trust.stat", lc, { n: CATALOG_COUNT })}
        </p>
      </section>

      <section id="join" className="start-join">
        <h2 className="start-join-heading">{t("start.join.heading", lc)}</h2>
        <div className="start-join-cards">
          <article
            className={`start-card start-card-paid ${codeMode ? "is-secondary" : "is-primary"}`}
            aria-labelledby="card-paid-label"
          >
            <div className="start-card-label" id="card-paid-label">
              {t("start.join.paid.label", lc)}
            </div>
            <div className="start-card-price">
              {t("start.join.paid.price", lc, { price: price.displayString })}
            </div>
            <ul className="start-card-features">
              <li>{t("start.join.paid.feat_1", lc)}</li>
              <li>{t("start.join.paid.feat_2", lc)}</li>
              <li>{t("start.join.paid.feat_3", lc)}</li>
            </ul>
            <label className="start-field">
              <span className="start-field-label">{t("start.join.email_label", lc)}</span>
              <input
                type="email"
                inputMode="email"
                autoComplete="email"
                placeholder={t("start.join.email_placeholder", lc)}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submitting}
                aria-invalid={error && error.card === "paid" ? "true" : "false"}
              />
            </label>
            <button
              type="button"
              className="start-card-cta start-card-cta-primary"
              onClick={() => handleSubmit("paid")}
              disabled={submitting}
            >
              {t("start.join.paid.cta", lc)}
            </button>
            {error && error.card === "paid" && (
              <p className="start-card-error" role="alert">{error.message}</p>
            )}
            <p className="start-card-sub">{t("start.join.paid.sub", lc)}</p>
          </article>

          <article
            className={`start-card start-card-code ${codeMode ? "is-primary" : "is-secondary"}`}
            aria-labelledby="card-code-label"
          >
            <div className="start-card-label" id="card-code-label">
              {t("start.join.code.label", lc)}
            </div>
            <p className="start-card-description">{t("start.join.code.description", lc)}</p>
            <label className="start-field">
              <span className="start-field-label">{t("start.join.email_label", lc)}</span>
              <input
                type="email"
                inputMode="email"
                autoComplete="email"
                placeholder={t("start.join.email_placeholder", lc)}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submitting}
                aria-invalid={error && error.card === "code" ? "true" : "false"}
              />
            </label>
            <label className="start-field">
              <span className="start-field-label">{t("start.join.code.label", lc)}</span>
              <input
                type="text"
                autoComplete="off"
                placeholder={t("start.join.code.placeholder", lc)}
                value={promoCode}
                onChange={(e) => setPromoCode(e.target.value.toUpperCase())}
                disabled={submitting}
                aria-invalid={error && error.card === "code" ? "true" : "false"}
              />
            </label>
            <button
              type="button"
              className="start-card-cta start-card-cta-secondary"
              onClick={() => handleSubmit("code")}
              disabled={submitting}
            >
              {t("start.join.code.cta", lc)}
            </button>
            {error && error.card === "code" && (
              <p className="start-card-error" role="alert">{error.message}</p>
            )}
          </article>
        </div>
      </section>

      <footer className="start-footer">
        <div className="start-footer-brand">
          <PulpoLogo size={20} />
        </div>
        <div className="start-footer-links">
          <a href="/legal">{t("start.footer.privacy", lc)}</a>
          <span aria-hidden="true">·</span>
          <a href="/legal">{t("start.footer.terms", lc)}</a>
          <span aria-hidden="true">·</span>
          <span className="start-footer-stripe">{t("start.footer.stripe", lc)}</span>
        </div>
      </footer>

      {stickyVisible && (
        <div className="start-sticky-cta" role="region" aria-label="Sticky upgrade CTA">
          <button
            type="button"
            className="start-cta-primary"
            onClick={scrollToJoin}
          >
            {t("start.sticky_cta", lc, { price: price.displayString })}
          </button>
        </div>
      )}
    </div>
  );
}
