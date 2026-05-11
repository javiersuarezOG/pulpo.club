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
const COUNTRY_TO_CURRENCY = {
  // ── USD region (also default for unmapped diaspora geos) ──
  SV: "usd",  // El Salvador — legal tender USD since 2001
  US: "usd",
  CA: "usd",  // close enough; diaspora-facing, not a CAD market today
  GB: "usd",  // UK diaspora — easier than carrying GBP for one country
  AU: "usd",
  AE: "usd",
  // ── EUR region ──
  ES: "eur",  // Spain diaspora — large EU node
  DE: "eur",
  FR: "eur",
  IT: "eur",
  NL: "eur",
  BE: "eur",
  AT: "eur",
  IE: "eur",
  PT: "eur",
  // ── MXN region ──
  MX: "mxn",
  // ── ARS region ──
  AR: "ars",
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
