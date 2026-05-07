// Shared helpers for the Stripe Managed Payments integration.
//
// Followed Stripe blueprint guidance: leave the Stripe SDK at its
// default API version, override per-request to "2026-02-25.preview"
// only on calls that need Managed Payments. That keeps the rest of
// the SDK on the stable contract.
//
// Required env vars (set in Vercel project + .env locally):
//   STRIPE_SECRET_KEY      — sk_test_… or sk_live_…
//   STRIPE_WEBHOOK_SECRET  — whsec_… (from the Stripe webhook endpoint config)
//   STRIPE_PRICE_ID_PRO    — price_… (output of automation/stripe_setup.mjs)
//   CLERK_SECRET_KEY       — sk_test_… or sk_live_… from Clerk dashboard

const Stripe = require("stripe");
const { clerkClient } = require("../_clerk");

// Header version for Managed Payments calls. Per the blueprint,
// Checkout Sessions with managed_payments=true require this.
const MANAGED_PAYMENTS_VERSION = "2026-02-25.preview";

let _stripe = null;
function stripeClient() {
  if (_stripe) return _stripe;
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) throw new Error("STRIPE_SECRET_KEY not set");
  _stripe = new Stripe(key);
  return _stripe;
}

// Vercel parses JSON bodies automatically, but Stripe's signature
// verification needs the *exact* raw bytes. Read them off the request
// stream — the `bodyParser: false` config below stops Vercel from
// consuming the stream first.
async function readRawBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  return Buffer.concat(chunks);
}

// Single-line, grep-friendly log. Matches api/login.js's convention.
function logApi(name, fields) {
  const parts = [`[api]`, name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

module.exports = {
  MANAGED_PAYMENTS_VERSION,
  stripeClient,
  clerkClient,
  readRawBody,
  logApi,
};
