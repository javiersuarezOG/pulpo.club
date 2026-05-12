// POST /api/stripe/start-checkout
//
// Public Stripe Checkout entry — no Clerk session required. Used by the
// /start marketing landing page. Takes an email + optional promo code +
// UTMs, picks a presentment currency from the visitor's geo, and returns
// a Stripe-hosted Checkout URL.
//
// The companion change in api/stripe/webhook.js detects sessions created
// here (by the absence of `client_reference_id`) and creates the Clerk
// user via an invitation after `checkout.session.completed` fires.
//
// Auth: none. Rate-limited per (ip, email) to 5 attempts / 60s.
//
// Env vars (already configured for the auth-gated endpoint):
//   STRIPE_SECRET_KEY     — sk_test_… / sk_live_…
//   STRIPE_PRICE_ID_PRO   — price_… (multi-currency presentment)

const {
  MANAGED_PAYMENTS_VERSION,
  stripeClient,
  logApi,
} = require("./_stripe");
const { currencyForCountry, countryFromRequest } = require("./_geo");
const { hit: rateLimitHit } = require("./_rate_limit");
const posthog = require("../_posthog");

// Loose RFC 5321 email check — only rejects obvious garbage so the user
// sees Stripe's stricter validation rather than ours. Trims whitespace
// because mobile keyboards love adding trailing spaces.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Stripe Checkout's supported `locale` values. We only pass values the
// frontend can produce (en, es) and let Stripe handle everything else
// via its default "auto" behaviour.
const SUPPORTED_LOCALES = new Set(["en", "es"]);

function safeStr(v) {
  return typeof v === "string" ? v : "";
}

function pickUtms(body) {
  return {
    utm_source:   safeStr(body.utm_source).slice(0, 100),
    utm_medium:   safeStr(body.utm_medium).slice(0, 100),
    utm_campaign: safeStr(body.utm_campaign).slice(0, 100),
    utm_term:     safeStr(body.utm_term).slice(0, 100),
    utm_content:  safeStr(body.utm_content).slice(0, 100),
  };
}

async function readJsonBody(req) {
  // Vercel parses JSON bodies on Node functions automatically, but the
  // raw-body case (e.g. local Stripe CLI replay) still falls through —
  // read the stream if `req.body` is missing.
  if (req.body && typeof req.body === "object") return req.body;
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return {};
  try { return JSON.parse(raw); } catch { return {}; }
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi("stripe.start_checkout", {
      status: 405, ms: Date.now() - t0, reason: "method",
    });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const priceId = process.env.STRIPE_PRICE_ID_PRO;
  if (!priceId) {
    logApi("stripe.start_checkout", {
      status: 500, ms: Date.now() - t0, reason: "missing_price_id",
    });
    return res.status(500).json({ error: "stripe_not_configured" });
  }

  const body = await readJsonBody(req);
  // Email is now OPTIONAL on this endpoint. The /start landing page
  // doesn't collect it — Stripe Checkout's hosted page asks for it
  // when `customer_email` is unset. The webhook later reads
  // session.customer_details.email regardless of who provided it.
  // Backward-compat: any caller that DOES send an email gets the
  // pre-validated + pre-filled behaviour.
  const rawEmail = safeStr(body.email).trim().toLowerCase();
  const email = rawEmail && EMAIL_RE.test(rawEmail) && rawEmail.length <= 254
    ? rawEmail
    : null;
  const promoCode = safeStr(body.promoCode).trim().toUpperCase();
  const locale = SUPPORTED_LOCALES.has(safeStr(body.locale))
    ? body.locale === "es" ? "es-419" : "en"
    : null;
  const utms = pickUtms(body);

  // Distinct ID used for every PostHog event below — hashed email when
  // available so we can chain anonymous client-side events through the
  // server-side funnel via PostHog's alias machinery.
  const distinctId = posthog.emailDistinctId(email);

  // If a non-empty email was supplied but failed validation, surface a
  // 400 so the caller knows to fix it. (Empty/missing email is fine.)
  if (rawEmail && !email) {
    logApi("stripe.start_checkout", {
      status: 400, ms: Date.now() - t0, reason: "invalid_email",
    });
    posthog.capture(distinctId, "start_checkout.rejected", {
      reason: "invalid_email", ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(400).json({ error: "invalid_email" });
  }

  // Rate limit per (IP, email-or-empty). Without an email we throttle
  // per-IP only — fine, since the limiter exists to stop scripted abuse,
  // not to deduplicate legitimate users.
  const rl = rateLimitHit(req, email || "");
  if (!rl.allowed) {
    res.setHeader("Retry-After", String(Math.ceil(rl.retryAfterMs / 1000)));
    logApi("stripe.start_checkout", {
      status: 429, ms: Date.now() - t0, reason: "rate_limited", retry_ms: rl.retryAfterMs,
    });
    posthog.capture(distinctId, "start_checkout.rejected", {
      reason: "rate_limited", retry_ms: rl.retryAfterMs, ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(429).json({ error: "rate_limited" });
  }

  // Resolve geo → presentment currency. The Price object in Stripe has
  // currency_options for USD/EUR/MXN/ARS; passing `currency` picks one.
  const country = countryFromRequest(req);
  const currency = currencyForCountry(country);

  // Resolve the promo code if present. Stripe rejects combinations of
  // `discounts: [...]` and `allow_promotion_codes: true` — pick one.
  let discounts = null;
  if (promoCode) {
    try {
      const codes = await stripeClient().promotionCodes.list({
        code: promoCode,
        active: true,
        limit: 1,
      });
      if (!codes.data || codes.data.length === 0) {
        // Surface a key prefix in the log so a test/live key mismatch
        // (the most common cause of "no code found") is one grep away.
        const keyPrefix = (process.env.STRIPE_SECRET_KEY || "").slice(0, 7);
        logApi("stripe.start_checkout", {
          status: 400, ms: Date.now() - t0, reason: "invalid_promo_code",
          code: promoCode, key_prefix: keyPrefix,
        });
        posthog.capture(distinctId, "start_checkout.rejected", {
          reason: "invalid_promo_code", promo_code: promoCode,
          stripe_key_prefix: keyPrefix, ms: Date.now() - t0,
        });
        await posthog.flush();
        return res.status(400).json({ error: "invalid_promo_code" });
      }
      discounts = [{ promotion_code: codes.data[0].id }];
    } catch (err) {
      logApi("stripe.start_checkout", {
        status: 500, ms: Date.now() - t0, reason: "promo_lookup_failed",
        error: err && err.message,
      });
      posthog.capture(distinctId, "start_checkout.failed", {
        reason: "promo_lookup_failed", error_message: err && err.message,
        ms: Date.now() - t0,
      });
      await posthog.flush();
      return res.status(500).json({ error: "promo_lookup_failed" });
    }
  }

  const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
  const host = req.headers["x-forwarded-host"] || req.headers.host;
  const origin = `${proto}://${host}`;

  const sessionMetadata = {
    source: "start",
    country: country || "",
    ...utms,
  };

  const sessionParams = {
    mode: "subscription",
    managed_payments: { enabled: true },
    line_items: [{ price: priceId, quantity: 1 }],
    currency,
    // No client_reference_id — that's the signal to the webhook that this
    // is an anonymous /start flow that should resolve the user via email
    // (which the webhook reads from session.customer_details.email,
    // populated either by Stripe's hosted form or by our customer_email
    // pre-fill below).
    subscription_data: {
      metadata: sessionMetadata,
    },
    metadata: sessionMetadata,
    success_url: `${origin}/welcome?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url:  `${origin}/start?cancelled=1`,
  };

  // Pre-fill email on the Stripe form when we have it; otherwise let
  // Stripe collect it. Don't stamp the session subscription metadata
  // with email when we don't have one — keeps the data honest.
  if (email) {
    sessionParams.customer_email = email;
    sessionParams.subscription_data.metadata.email = email;
  }

  if (discounts) {
    sessionParams.discounts = discounts;
  } else {
    // Let the user enter a code on Stripe's hosted page if they didn't
    // pre-fill via URL. Mirrors api/stripe/create-checkout-session.js.
    sessionParams.allow_promotion_codes = true;
  }

  if (locale) sessionParams.locale = locale;

  let session;
  try {
    session = await stripeClient().checkout.sessions.create(sessionParams, {
      apiVersion: MANAGED_PAYMENTS_VERSION,
    });
  } catch (err) {
    logApi("stripe.start_checkout", {
      status: 500, ms: Date.now() - t0, reason: "stripe_error", error: err.message,
    });
    posthog.capture(distinctId, "start_checkout.failed", {
      reason: "stripe_error", error_message: err.message, ms: Date.now() - t0,
    });
    await posthog.flush();
    return res.status(500).json({ error: "stripe_error", message: err.message });
  }

  logApi("stripe.start_checkout", {
    status: 200, ms: Date.now() - t0,
    session_id: session.id,
    currency, country: country || "?",
    has_promo: discounts ? 1 : 0,
    locale: locale || "auto",
    utm_source: utms.utm_source || "",
    utm_campaign: utms.utm_campaign || "",
  });
  posthog.capture(distinctId, "start_checkout.session_created", {
    session_id: session.id,
    currency, country: country || "",
    has_promo: !!discounts,
    has_email_prefill: !!email,
    locale: locale || "auto",
    utm_source: utms.utm_source || "",
    utm_medium: utms.utm_medium || "",
    utm_campaign: utms.utm_campaign || "",
    utm_term: utms.utm_term || "",
    utm_content: utms.utm_content || "",
    ms: Date.now() - t0,
  });
  await posthog.flush();
  return res.status(200).json({ url: session.url, sessionId: session.id });
};
