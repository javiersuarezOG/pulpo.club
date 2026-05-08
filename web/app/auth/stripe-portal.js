// Client-side helper for the "Manage plan" flow on the Account page.
//
// Calls /api/stripe/billing-portal and redirects the browser to the
// Stripe Customer Portal URL. Stripe handles card updates, plan
// changes, cancellation, and invoice history; the user comes back to
// /preview/?account=subscription when they're done (configured
// server-side).
//
// Mirrors stripe-checkout.js — single-purpose helper, same telemetry
// conventions, same onError contract.

import { track } from "../telemetry/hook";

export async function openStripePortal({ onError } = {}) {
  track("portal.opened", {});
  let res;
  try {
    res = await fetch("/api/stripe/billing-portal", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (err) {
    track("portal.error", { reason: "network" });
    if (onError) onError("network", err);
    return false;
  }

  if (!res.ok) {
    let detail = null;
    try { detail = await res.json(); } catch {}
    const reason = detail && detail.error ? detail.error : `http_${res.status}`;
    track("portal.error", { reason });
    try {
      track("api.error", {
        endpoint: "/api/stripe/billing-portal",
        status: res.status,
        reason,
        detail: detail && detail.detail,
      });
    } catch {}
    if (onError) onError(reason, detail);
    return false;
  }

  const { url } = await res.json();
  if (!url) {
    track("portal.error", { reason: "no_url" });
    if (onError) onError("no_url");
    return false;
  }
  window.location.assign(url);
  return true;
}
