// Pricing display helper for every paid-CTA surface (hero microcopy, USP
// band, /start hero + sticky CTA, FreeMonthModal, UspPopup, PlansPage).
//
// ────────────────────────────────────────────────────────────────────
// Single source of truth for the Pulpo Pro subscription price.
// ────────────────────────────────────────────────────────────────────
//
// To change the displayed price:
//   1. Edit the `amount` and `displayString` in `PRICES` below.
//   2. In Stripe Dashboard → Products → Pulpo Pro → "Add another price",
//      create a new monthly recurring Price with `currency_options` for
//      EUR and USD (and any other currency in PRICES below) at the new
//      amount. Same `recurring.interval = month`, same `tax_code =
//      txcd_10103100`. Archive the old Price.
//   3. Update STRIPE_PRICE_ID_PRO in Vercel (production scope) with the
//      new price_… ID. Redeploy.
//   4. Walk the live Checkout flow on the Vercel preview before merging
//      per CLAUDE.md's live-preview verification mandate.
//
// To add a new currency (e.g. MXN):
//   1. Widen the `Currency` union with the new code (lowercase ISO 4217).
//   2. Add a row to `PRICES` with the amount + displayString.
//   3. Add the country → currency rows to `COUNTRY_TO_CURRENCY` below.
//   4. Mirror the country → currency rows into `api/stripe/_geo.js`
//      (server-side; runs on Vercel Node — sibling file, must agree).
//   5. Add a matching `currency_options` row on the Stripe Price.
//
// The server-side _geo.js holds the parallel country → currency map.
// Both files must agree; if they drift, marketing advertises one
// currency and Stripe charges another. The duplication exists because
// _geo.js is CJS Node code and this file is ESM TypeScript bundled for
// the browser — sharing across that boundary costs more than the bug it
// prevents.

export type Currency = "eur" | "usd";

export type PriceDisplay = {
  currency: Currency;
  // Amount in the major unit (e.g. 4.99 for €4.99).
  amount: number;
  // Pre-formatted display string with currency glyph + amount, e.g.
  // "€4.99" / "$4.99". Used directly in CTA copy via the {price}
  // placeholder in UI_STRINGS — the glyph is carried by this string,
  // not hard-coded in the i18n template.
  displayString: string;
};

// Marketing prices. Must match the Stripe Price's `currency_options`
// rows. Editing the numbers here without also rotating the Stripe Price
// (see the rotation playbook above) ships a "marketing says X, Checkout
// charges Y" trust break — the exact failure mode api/geo.js was built
// to prevent.
export const PRICES: Record<Currency, PriceDisplay> = {
  eur: { currency: "eur", amount: 4.99, displayString: "€4.99" },
  usd: { currency: "usd", amount: 4.99, displayString: "$4.99" },
};

const DEFAULT_CURRENCY: Currency = "usd";

// Locale-aware price string for surfaces that show BOTH currencies in one
// sentence (legal copy) or otherwise can't use the geo-resolved {price}
// placeholder. Applies the ES decimal-comma convention to EUR only — ES
// legal copy writes "€4,99" but keeps "$4.99" for USD (matches how the
// subscription policy was originally hand-written). Everything derives from
// the `amount` in PRICES above, so a price change here is still one edit.
export function priceDisplay(currency: Currency, locale: string = "en"): string {
  const { amount } = PRICES[currency];
  if (currency === "eur" && locale === "es") {
    return `€${amount.toFixed(2).replace(".", ",")}`;
  }
  return PRICES[currency].displayString;
}

// Country → currency. Uppercase ISO 3166-1 alpha-2. Must mirror
// api/stripe/_geo.js — see the header comment. Any country not in the
// map resolves to DEFAULT_CURRENCY via priceForCountry() below.
const COUNTRY_TO_CURRENCY: Record<string, Currency> = {
  // ── EUR region (mirrors _geo.js) ──
  ES: "eur",
  DE: "eur",
  FR: "eur",
  IT: "eur",
  NL: "eur",
  BE: "eur",
  AT: "eur",
  IE: "eur",
  PT: "eur",
  // Every other country (El Salvador, US, CA, GB, AU, AE, MX, AR, …)
  // resolves to DEFAULT_CURRENCY (USD) until added here AND to the
  // Stripe Price's currency_options.
};

// Map a (possibly null/lowercase/garbage) country code to the display
// price. Unknown geos fall back to USD — matches _geo.js's behaviour.
export function priceForCountry(cc: string | null | undefined): PriceDisplay {
  if (!cc || typeof cc !== "string") return PRICES[DEFAULT_CURRENCY];
  const upper = cc.trim().toUpperCase();
  const currency = COUNTRY_TO_CURRENCY[upper];
  if (currency) return PRICES[currency];
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
