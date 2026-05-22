// One-shot Stripe bootstrap for Pulpo Pro.
//
// Idempotent: looks up an existing product by name first, and only
// creates one if missing. The product carries a default monthly price
// in EUR. Prints the price ID at the end — paste it into Vercel +
// .env as STRIPE_PRICE_ID_PRO.
//
// Run locally with the test secret key in your env:
//   STRIPE_SECRET_KEY=sk_test_… node automation/stripe_setup.mjs
//
// Per the Stripe blueprint: tax_code "txcd_10103100" (digital service
// / SaaS) and the 2026-02-25.preview header for product creation
// because we'll bind it to a Managed Payments Checkout Session.

import "dotenv/config";
import Stripe from "stripe";

const PRODUCT_NAME      = "Pulpo Pro";
const PRODUCT_DESC      = "Pulpo Pro — off-market access, broker contacts, unlimited views, unlimited saves.";
const PRICE_AMOUNT      = 999;           // €9.99 / month (999 cents) — mirror web/app/lib/pricing.ts
const PRICE_CURRENCY    = "eur";
const PRICE_INTERVAL    = "month";
const TAX_CODE          = "txcd_10103100"; // digital service / SaaS
const PREVIEW_VERSION   = "2026-02-25.preview";

function priceId(p) {
  if (!p.default_price) return null;
  return typeof p.default_price === "string" ? p.default_price : p.default_price.id;
}

async function main() {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) {
    console.error("STRIPE_SECRET_KEY not set. Add it to .env and re-run.");
    process.exit(2);
  }
  const stripe = new Stripe(key);

  // Idempotency by product name. Stripe doesn't enforce unique names,
  // so this is a soft contract — only re-run will create dupes if you
  // change PRODUCT_NAME.
  const existing = await stripe.products.list({ limit: 100, active: true });
  let product = existing.data.find((p) => p.name === PRODUCT_NAME);

  if (product) {
    console.log(`[stripe-setup] Product exists: ${product.id} (${product.name})`);
  } else {
    product = await stripe.products.create(
      {
        name:        PRODUCT_NAME,
        description: PRODUCT_DESC,
        tax_code:    TAX_CODE,
        default_price_data: {
          unit_amount: PRICE_AMOUNT,
          currency:    PRICE_CURRENCY,
          recurring:   { interval: PRICE_INTERVAL },
        },
      },
      { apiVersion: PREVIEW_VERSION },
    );
    console.log(`[stripe-setup] Created product: ${product.id}`);
  }

  const id = priceId(product);
  if (!id) {
    console.error("[stripe-setup] Product has no default_price. " +
      "Either delete it in the dashboard and re-run, or attach a price manually.");
    process.exit(3);
  }

  console.log("");
  console.log("============================================================");
  console.log("Set this in Vercel project → Settings → Environment Variables");
  console.log("(and in your local .env for development):");
  console.log("");
  console.log(`  STRIPE_PRICE_ID_PRO=${id}`);
  console.log("");
  console.log("Then redeploy / restart vite dev for the API endpoint to pick");
  console.log("it up.");
  console.log("============================================================");
}

main().catch((err) => {
  console.error("[stripe-setup] failed:", err && err.message ? err.message : err);
  process.exit(1);
});
