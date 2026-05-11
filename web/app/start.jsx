// /start — public marketing landing for the acquisition funnel.
//
// Single-button page. No email input. No promo code input. Stripe's
// hosted checkout page collects both — Stripe asks for the email
// automatically when `customer_email` is unset, and exposes a native
// "Add promotion code → Apply" affordance for codes.
//
// Flow:
//   click "Get access" → POST /api/stripe/start-checkout
//                      → window.location.assign(stripeUrl)
//                      → user pays on Stripe-hosted page (email + code
//                        entered there)
//                      → returns to /welcome (anonymous flow)
//
// URL behaviours:
//   ?code=REDDIT01   → silently pre-applies the code on the Stripe
//                      session via `discounts: [...]`. The visitor sees
//                      a discount line item on Stripe without typing —
//                      a "✓ Discount applied at checkout" note renders
//                      on /start as feedback.
//                      If the code is invalid (typo, exhausted, test-vs-
//                      live mismatch) we silently retry without it so
//                      the visitor never dead-ends on a broken link.
//   ?utm_source=…    → captured into sessionStorage and posted to the
//                      API, then propagated onto the Clerk user via
//                      the webhook (acquisition attribution).
//   ?cancelled=1     → renders a soft notice (came back from Stripe).
//
// Mount: app.jsx branches on the pathname before <App /> renders, so
// /start has no TopNav / BottomNav / footer / ListingsProvider overhead.

import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { t, useLocale } from "./i18n.jsx";
import { PulpoLogo } from "./components.jsx";
import { track } from "./telemetry/hook";
import { priceForCountry, fetchPriceForCurrentGeo } from "./lib/pricing";
import "./styles/start.css";

// Total catalog size — surfaced in the trust strip. Hardcoded for v1;
// follow-up adds a /api/catalog-count endpoint or a build-time env var.
const CATALOG_COUNT = 900;

// Hero photo. Sits in web/photos/, served via the /photos/:file rewrite
// in vercel.json. CSS gradient renders synchronously underneath as the
// first paint, so the hero never shows a blank slot.
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
  const [locale] = useLocale();
  const lc = locale;

  // `?code=` is honored server-side only. We render an acknowledgement
  // note ("✓ Discount applied at checkout") but never the code itself
  // as an input field — Stripe's hosted page handles that surface.
  const urlCode = useMemo(() => {
    const c = readQueryParam("code");
    return c ? c.trim().toUpperCase() : "";
  }, []);
  const initialCancelled = useMemo(() => readQueryParam("cancelled") === "1", []);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [price, setPrice] = useState(() => priceForCountry(null));
  const [stickyVisible, setStickyVisible] = useState(false);
  const heroSentinelRef = useRef(null);

  const utms = useMemo(() => captureUtms(), []);

  useEffect(() => {
    track("start.viewed", { has_code: urlCode.length > 0 });
  }, [urlCode]);

  useEffect(() => {
    let cancelled = false;
    fetchPriceForCurrentGeo().then((p) => {
      if (!cancelled) setPrice(p);
    });
    return () => { cancelled = true; };
  }, []);

  // Mobile sticky CTA — appears once the hero CTA has scrolled out of
  // view (sentinel placed just below the hero block). Hidden on desktop
  // via CSS @media query at 1024px+.
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

  // Internal — call once with the URL-supplied code, and again without
  // it if the first call 400s on invalid_promo_code. Soft-fail: never
  // dead-end the user on a broken campaign URL.
  const postCheckout = useCallback(
    async (includeCode) => {
      const res = await fetch("/api/stripe/start-checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          promoCode: includeCode && urlCode ? urlCode : null,
          locale: lc,
          ...utms,
        }),
      });
      return res;
    },
    [urlCode, lc, utms]
  );

  const handleSubmit = useCallback(
    async () => {
      setError(null);
      track("start.cta_clicked", { has_code: urlCode.length > 0 });

      setSubmitting(true);
      try {
        let res = await postCheckout(true);
        // Soft-fail on a bad URL code — retry without it so the user
        // still gets to Stripe (without the discount). Telemetry fires
        // so we can clean up broken campaign URLs from PostHog.
        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          const reason = detail && detail.error;
          if (reason === "invalid_promo_code" && urlCode) {
            track("start.code_error_shown", { reason: "invalid_promo_code" });
            res = await postCheckout(false);
          } else if (reason === "rate_limited") {
            setError(t("start.error.rate_limited", lc));
            setSubmitting(false);
            return;
          } else {
            track("api.error", {
              endpoint: "/api/stripe/start-checkout",
              status: res.status,
              reason: reason,
              detail: detail && detail.detail,
            });
            setError(t("start.error.generic", lc));
            setSubmitting(false);
            return;
          }
        }

        const data = await res.json();
        if (!data || !data.url) {
          setError(t("start.error.generic", lc));
          setSubmitting(false);
          return;
        }
        track("start.checkout_redirected", { had_promo_code: urlCode.length > 0 });
        window.location.assign(data.url);
      } catch (err) {
        track("api.error", {
          endpoint: "/api/stripe/start-checkout",
          status: 0,
          reason: "network",
          detail: err && err.message,
        });
        setError(t("start.error.generic", lc));
        setSubmitting(false);
      }
    },
    [lc, urlCode, postCheckout]
  );

  const scrollToJoin = useCallback(() => {
    const el = document.getElementById("join");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  return (
    <div className="start-page">
      <header className="start-nav">
        <a href="/" className="start-logo" aria-label={t("start.aria.logo_home", lc)}>
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

      <section className="start-trust" aria-label={t("start.aria.social_proof", lc)}>
        <p className="start-trust-stat">
          {t("start.trust.stat", lc, { n: CATALOG_COUNT })}
        </p>
      </section>

      <section id="join" className="start-join">
        <h2 className="start-join-heading">{t("start.join.heading", lc)}</h2>
        <div className="start-join-card">
          <div className="start-card-label">{t("start.join.paid.label", lc)}</div>
          <div className="start-card-price">
            {t("start.join.paid.price", lc, { price: price.displayString })}
          </div>
          <ul className="start-card-features">
            <li>{t("start.join.paid.feat_1", lc)}</li>
            <li>{t("start.join.paid.feat_2", lc)}</li>
            <li>{t("start.join.paid.feat_3", lc)}</li>
          </ul>
          <button
            type="button"
            className="start-card-cta start-card-cta-primary"
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting
              ? t("start.join.paid.cta_submitting", lc)
              : t("start.join.paid.cta", lc)}
          </button>
          {urlCode && (
            <p className="start-code-applied-note" aria-live="polite">
              {t("start.code.applied_note", lc)}
            </p>
          )}
          {error && (
            <p className="start-card-error" role="alert">{error}</p>
          )}
          <p className="start-card-sub">{t("start.join.paid.sub", lc)}</p>
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
        <div className="start-sticky-cta" role="region" aria-label={t("start.aria.sticky_cta", lc)}>
          <button
            type="button"
            className="start-cta-primary"
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting
              ? t("start.join.paid.cta_submitting", lc)
              : t("start.sticky_cta", lc, { price: price.displayString })}
          </button>
        </div>
      )}
    </div>
  );
}
