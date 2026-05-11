// Pricing display helper for /start.
//
// Mirror of api/stripe/_geo.js — both files must agree on which country
// gets which currency, or the marketing page advertises one price and
// Stripe charges another. v1 ships two currencies: EUR for EU diaspora,
// USD for everywhere else (default).
//
// Source of truth for the *amounts* is this file; the server-side
// _geo.js only knows the currency code. The Stripe Price object has
// matching `currency_options` for both rows — see
// docs/start-launch-ops.md for the dashboard setup.

export type Currency = "eur" | "usd";

export type PriceDisplay = {
  currency: Currency;
  // Integer amount in the major unit (€10, $10 — both display as "10").
  amount: number;
  // Pre-formatted display string with currency glyph + amount, e.g. "€10" / "$10".
  displayString: string;
};

// Marketing prices. Match the Stripe Price's `currency_options` rows.
const PRICES: Record<Currency, PriceDisplay> = {
  eur: { currency: "eur", amount: 10, displayString: "€10" },
  usd: { currency: "usd", amount: 10, displayString: "$10" },
};

const EUR_COUNTRIES = new Set([
  "ES", "DE", "FR", "IT", "NL", "BE", "AT", "IE", "PT",
]);

const DEFAULT_CURRENCY: Currency = "usd";

// Map a (possibly null/lowercase/garbage) country code to the display
// price. Unknown geos fall back to USD — matches _geo.js's behaviour.
export function priceForCountry(cc: string | null | undefined): PriceDisplay {
  if (!cc || typeof cc !== "string") return PRICES[DEFAULT_CURRENCY];
  const upper = cc.trim().toUpperCase();
  if (EUR_COUNTRIES.has(upper)) return PRICES.eur;
  return PRICES[DEFAULT_CURRENCY];
}

// Convenience: fetch /api/geo (Vercel-edge-derived) and resolve to the
// display price. Falls back to USD on any error so the hero always renders
// a price, even if the geo endpoint is down or the request is offline.
export async function fetchPriceForCurrentGeo(): Promise<PriceDisplay> {
  try {
    const res = await fetch("/api/geo", { credentials: "omit" });
    if (!res.ok) return PRICES[DEFAULT_CURRENCY];
    const data = (await res.json()) as { country?: string | null; currency?: string };
    return priceForCountry(data && data.country ? data.country : null);
  } catch {
    return PRICES[DEFAULT_CURRENCY];
  }
}
