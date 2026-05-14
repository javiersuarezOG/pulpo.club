// Client-side helper for the "Upgrade to Pro" flow.
//
// Calls the server endpoint /api/stripe/create-checkout-session, then
// redirects the browser to the Stripe-hosted Checkout URL. Stripe
// handles card entry, tax, and routing back to /preview/?upgrade=… on
// completion.
//
// The signed-in Clerk session cookie is sent automatically because the
// fetch is same-origin.
//
// Wave-2: forwards promo code + UTMs from URL/sessionStorage so a user
// who lands at /?code=PULPO20, navigates to /plans, and clicks Upgrade
// gets the discount applied at Stripe. Behind the
// promo_code_forwarding_v2 feature flag — when off, posts an empty body
// (pre-Wave-2 behavior).

import { track } from "../telemetry/hook";
import { captureCampaignParams } from "../lib/campaign";
import { readFeatureFlag } from "../lib/feature-flag";

export async function startStripeCheckout({ onError } = {}) {
  // Wave-2: build the POST body from same-session campaign params.
  // Empty body when the flag is off (rollback path).
  let body = "{}";
  let hasPromo = false;
  try {
    if (readFeatureFlag("promo_code_forwarding_v2", true)) {
      const { urlCode, utms } = captureCampaignParams();
      const payload = {};
      if (urlCode) {
        payload.promoCode = urlCode;
        hasPromo = true;
      }
      for (const [k, v] of Object.entries(utms || {})) {
        if (v) payload[k] = v;
      }
      if (Object.keys(payload).length > 0) {
        body = JSON.stringify(payload);
      }
    }
  } catch {
    // Defensive: any read failure → empty body, no regression.
    body = "{}";
    hasPromo = false;
  }

  track("upgrade.checkout_started", { has_promo: hasPromo });
  let res;
  try {
    res = await fetch("/api/stripe/create-checkout-session", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch (err) {
    if (onError) onError("network", err);
    return false;
  }

  if (!res.ok) {
    let detail = null;
    try { detail = await res.json(); } catch {}
    try {
      track("api.error", {
        endpoint: "/api/stripe/create-checkout-session",
        status: res.status,
        reason: detail && detail.error,
        detail: detail && detail.detail,
      });
    } catch {}
    if (onError) onError(detail && detail.error ? detail.error : `http_${res.status}`, detail);
    return false;
  }

  const { url } = await res.json();
  if (!url) {
    if (onError) onError("no_url");
    return false;
  }
  window.location.assign(url);
  return true;
}
