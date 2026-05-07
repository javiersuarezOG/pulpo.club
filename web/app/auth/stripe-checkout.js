// Client-side helper for the "Upgrade to Pro" flow.
//
// Calls the server endpoint /api/stripe/create-checkout-session, then
// redirects the browser to the Stripe-hosted Checkout URL. Stripe
// handles card entry, tax, and routing back to /preview/?upgrade=… on
// completion.
//
// The signed-in Clerk session cookie is sent automatically because the
// fetch is same-origin.

export async function startStripeCheckout({ onError } = {}) {
  let res;
  try {
    res = await fetch("/api/stripe/create-checkout-session", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (err) {
    if (onError) onError("network", err);
    return false;
  }

  if (!res.ok) {
    let detail = null;
    try { detail = await res.json(); } catch {}
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
