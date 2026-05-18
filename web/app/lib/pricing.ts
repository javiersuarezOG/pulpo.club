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
//
// Module-level cache: a single anon session can ask for the price from
// 5+ surfaces (hero microcopy, USP h2, FreeMonthModal, ProUpsellModal,
// /start). Without a cache that's 5 round-trips. We cache the resolved
// PriceDisplay after the first successful call, and dedupe concurrent
// in-flight requests so multiple components mounting on the same frame
// share one fetch.
let cachedPrice: PriceDisplay | null = null;
let inFlight: Promise<PriceDisplay> | null = null;

export async function fetchPriceForCurrentGeo(): Promise<PriceDisplay> {
  if (cachedPrice) return cachedPrice;
  if (inFlight) return inFlight;
  inFlight = (async () => {
    try {
      const res = await fetch("/api/geo", { credentials: "omit" });
      if (!res.ok) {
        // Don't cache on failure — let the next call retry. The caller
        // already has a USD fallback rendered, so retry is cheap.
        return PRICES[DEFAULT_CURRENCY];
      }
      const data = (await res.json()) as { country?: string | null; currency?: string };
      const resolved = priceForCountry(data && data.country ? data.country : null);
      cachedPrice = resolved;
      return resolved;
    } catch {
      return PRICES[DEFAULT_CURRENCY];
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

// Test-only escape hatch — clears the cache so unit tests don't bleed
// state across cases. Not used in production code.
export function _resetGeoPriceCacheForTests(): void {
  cachedPrice = null;
  inFlight = null;
}
