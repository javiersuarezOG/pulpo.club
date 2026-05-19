// GET /api/geo
//
// Tiny edge-derived geo lookup. The /start marketing page calls this once
// on mount to render the right currency + price in the hero CTA before
// the user is sent to Stripe Checkout. Without it the user might see
// "€10/month" then land on a Stripe page in MXN — a trust hit at the
// worst possible moment.
//
// Source of truth for the country → currency map is api/stripe/_geo.js;
// this endpoint just exposes that decision to the frontend. The matching
// display amounts live in web/app/lib/pricing.ts (lands in PR-B); for
// PR-A only the country + currency code are returned.

const { currencyForCountry, countryFromRequest } = require("./stripe/_geo");
const { makeRateLimiter, ipFromRequest, send429 } = require("./_rate_limit");

// 60 reads / 60s per IP. The endpoint is read-only and fronted by a 60s
// private edge cache (below), so a legit browser hits it once per page
// load at most. The cap is generous because shared NAT can multiplex
// real users; the goal is just to cut off script-driven abuse.
const geoLimiter = makeRateLimiter({
  windowMs: 60_000,
  maxAttempts: 60,
  name: "geo",
});

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const rl = geoLimiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    return send429(res, rl, "geo");
  }

  const country = countryFromRequest(req);
  const currency = currencyForCountry(country);
  // Short-lived edge cache — country is per-IP so we keep it private to
  // avoid any cross-user pollution downstream.
  res.setHeader("Cache-Control", "private, max-age=60");
  return res.status(200).json({
    country: country || null,
    currency,
  });
};
