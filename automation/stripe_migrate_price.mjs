// Migrate live Pulpo Pro subscriptions from one Price to another.
//
// Used when the displayed price changes (a price experiment) and we want
// EXISTING subscribers moved to the new amount rather than grandfathered on
// the old one. New checkouts already pick up the new price via the rotated
// STRIPE_PRICE_ID_PRO env var — this script only touches subscriptions that
// are still attached to the OLD price.
//
// Dry-run by default — prints exactly what it WOULD change and mutates
// nothing. Pass --apply to actually update the subscriptions.
//
//   # dry run (safe — no writes)
//   STRIPE_SECRET_KEY=sk_… node automation/stripe_migrate_price.mjs \
//     --from price_OLD --to price_NEW
//
//   # apply
//   STRIPE_SECRET_KEY=sk_… node automation/stripe_migrate_price.mjs \
//     --from price_OLD --to price_NEW --apply
//
// Proration:
//   --proration none               (DEFAULT) the new amount takes effect at
//                                   the next renewal — no mid-cycle credit or
//                                   charge. Cleanest for a price DROP.
//   --proration create_prorations  credit/charge the difference immediately.
//
// Re-running after --apply should report 0 remaining on --from. Once it does,
// archive the old Price in the Stripe Dashboard.
//
// Rollback: run again with --from and --to swapped.

import "dotenv/config";
import Stripe from "stripe";

function parseArgs(argv) {
  const out = { apply: false, proration: "none" };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--apply") out.apply = true;
    else if (a === "--from") out.from = argv[++i];
    else if (a === "--to") out.to = argv[++i];
    else if (a === "--proration") out.proration = argv[++i];
  }
  return out;
}

async function main() {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) {
    console.error("STRIPE_SECRET_KEY not set. Add it to .env and re-run.");
    process.exit(2);
  }
  const args = parseArgs(process.argv.slice(2));
  if (!args.from || !args.to) {
    console.error("Usage: node automation/stripe_migrate_price.mjs " +
      "--from price_OLD --to price_NEW [--proration none|create_prorations] [--apply]");
    process.exit(2);
  }
  if (args.from === args.to) {
    console.error("--from and --to are identical; nothing to migrate.");
    process.exit(2);
  }
  if (!["none", "create_prorations"].includes(args.proration)) {
    console.error(`Invalid --proration "${args.proration}". Use none | create_prorations.`);
    process.exit(2);
  }

  const stripe = new Stripe(key);
  const mode = args.apply ? "APPLY" : "DRY-RUN";
  console.log(`[migrate] ${mode} — from=${args.from} to=${args.to} proration=${args.proration}`);

  // Walk every subscription on the OLD price. Stripe's subscriptions.list
  // filters by price, and includes active + trialing + past_due etc. — we
  // migrate the ones that are still live (a canceled sub keeps its archived
  // price and needs no change).
  const LIVE = new Set(["active", "trialing", "past_due", "unpaid"]);
  let migrated = 0, skipped = 0, failed = 0, seen = 0;

  for await (const sub of stripe.subscriptions.list({ price: args.from, status: "all", limit: 100 })) {
    seen++;
    if (!LIVE.has(sub.status)) { skipped++; continue; }

    // Find the specific item on the old price (a sub could in theory carry
    // more than one line item; we only swap the matching one).
    const item = sub.items.data.find((it) => it.price && it.price.id === args.from);
    if (!item) { skipped++; continue; }

    const label = `${sub.id} (${sub.status}, cust=${sub.customer})`;
    if (!args.apply) {
      console.log(`  would migrate ${label}: item ${item.id} ${args.from} → ${args.to}`);
      migrated++;
      continue;
    }

    try {
      await stripe.subscriptions.update(sub.id, {
        items: [{ id: item.id, price: args.to }],
        proration_behavior: args.proration,
      });
      console.log(`  migrated  ${label}`);
      migrated++;
    } catch (err) {
      console.error(`  FAILED    ${label}: ${err && err.message ? err.message : err}`);
      failed++;
    }
  }

  console.log("");
  console.log("============================================================");
  console.log(`[migrate] ${mode} complete`);
  console.log(`  subscriptions on old price seen: ${seen}`);
  console.log(`  ${args.apply ? "migrated" : "would migrate"}:      ${migrated}`);
  console.log(`  skipped (not live / no item):    ${skipped}`);
  if (args.apply) console.log(`  failed:                          ${failed}`);
  if (!args.apply) console.log("  (dry run — re-run with --apply to make these changes)");
  console.log("============================================================");
  if (failed > 0) process.exit(1);
}

main().catch((err) => {
  console.error("[migrate] fatal:", err && err.message ? err.message : err);
  process.exit(1);
});
