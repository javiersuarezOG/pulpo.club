// Country → currency mapping for the public Checkout flow.
//
// Vercel attaches the visitor's two-letter country code on the
// `x-vercel-ip-country` header for every request (derived from edge geo).
// Without it (local dev, header stripped by a proxy), we fall back to USD
// — the diaspora's most common currency and El Salvador's legal tender.
//
// The matching display-side amounts live in web/app/lib/pricing.ts so the
// marketing page and the Stripe Checkout page never disagree. Adding a
// currency requires two edits: this map AND the price object in Stripe
// (Products → Pulpo Pro → currency_options).

const DEFAULT_CURRENCY = "usd";

// Lowercase ISO 4217 codes — Stripe expects lowercase in the Checkout
// Session `currency` param. Stripe accepts uppercase too but the SDK
// normalizes; staying lowercase keeps logs predictable.
//
// v1 ships two currencies (EUR + USD) — every other geo falls back to
// USD via the DEFAULT_CURRENCY. To add MXN/ARS later: add the rows
// here AND add the matching amounts to the Stripe Pulpo Pro Price
// (`currency_options`). Asking Stripe for a currency that isn't in
// the Price's options 500s the checkout, so the two MUST move together.
const COUNTRY_TO_CURRENCY = {
  // ── EUR region (must match the EUR row on the Pulpo Pro Price) ──
  ES: "eur",  // Spain diaspora — large EU node
  DE: "eur",
  FR: "eur",
  IT: "eur",
  NL: "eur",
  BE: "eur",
  AT: "eur",
  IE: "eur",
  PT: "eur",
  // Every other country resolves to USD via DEFAULT_CURRENCY below:
  //   - El Salvador (legal tender USD since 2001)
  //   - US, CA, GB, AU, AE — diaspora hubs
  //   - MX, AR, and every other unmapped geo — until we add their
  //     currencies to the Stripe Price.
};

// Map a country code to a currency, with a USD fallback for any country
// not in the explicit map. Case-insensitive; tolerant of bad input.
function currencyForCountry(cc) {
  if (!cc || typeof cc !== "string") return DEFAULT_CURRENCY;
  const upper = cc.trim().toUpperCase();
  return COUNTRY_TO_CURRENCY[upper] || DEFAULT_CURRENCY;
}

// Pull the country code from a Vercel-attached header. Returns null when
// the header is absent so the caller can decide whether to log the
// fallback or just take the default.
function countryFromRequest(req) {
  const h = req && req.headers && req.headers["x-vercel-ip-country"];
  if (!h || typeof h !== "string") return null;
  return h.trim().toUpperCase() || null;
}

module.exports = {
  DEFAULT_CURRENCY,
  COUNTRY_TO_CURRENCY,
  currencyForCountry,
  countryFromRequest,
};
