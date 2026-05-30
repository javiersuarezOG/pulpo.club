#!/usr/bin/env node
//
// scripts/backfill_resend_audience.mjs
//
// One-time backfill of Clerk Pro/Agency users into the Resend audience
// (RESEND_AUDIENCE_ID). Shipped alongside the Stripe-webhook wire that
// makes future Pro upgrades auto-enroll; this script catches up the
// existing 9 Pro users who were entitled in Clerk but never made it
// into the audience.
//
// USAGE:
//
//   # Dry-run — lists who WOULD be enrolled, doesn't call Resend
//   node scripts/backfill_resend_audience.mjs --dry-run
//
//   # Live — actually enrolls
//   node scripts/backfill_resend_audience.mjs
//
// REQUIRES:
//   CLERK_SECRET_KEY     — Clerk Backend API
//   RESEND_API_KEY       — Resend API
//   RESEND_AUDIENCE_ID   — the Pulpo audience to enroll into
//
// SAFETY:
//   • Idempotent — Resend dedupes on email; a contact that already
//     exists gets unsubscribed=false flipped via PATCH (handled by the
//     shared helper at api/_resend_audience.js).
//   • Best-effort per user: a failure on one contact logs + continues
//     to the next, so a single bad email doesn't abort the run.
//   • No-op on missing env: prints a clear "set X to enable" message
//     and exits 1 (so CI never silently runs a no-op).
//
// AFTER RUNNING:
//   curl https://pulpo.club/api/admin/newsletter/audience-count
//   → should show count = N matching Pro users (9 today, more later).

import { createClerkClient } from "@clerk/backend";
// _resend_audience.js is a CommonJS module — node ESM can require()
// from .mjs via createRequire.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { enrollPaidUserInAudience } = require("../api/_resend_audience.js");

const DRY_RUN = process.argv.includes("--dry-run");
const CLERK_PAGE_SIZE = 100;
const PRO_PLANS = new Set(["pro", "agency"]);

function die(msg) {
  console.error(`[backfill] ERROR: ${msg}`);
  process.exit(1);
}

if (!process.env.CLERK_SECRET_KEY) die("CLERK_SECRET_KEY is not set.");
if (!process.env.RESEND_API_KEY) die("RESEND_API_KEY is not set.");
if (!process.env.RESEND_AUDIENCE_ID) die("RESEND_AUDIENCE_ID is not set.");

const clerk = createClerkClient({
  secretKey: process.env.CLERK_SECRET_KEY,
  // Publishable key not needed for the Backend API enumeration here.
  publishableKey: process.env.CLERK_PUBLISHABLE_KEY
    || process.env.VITE_CLERK_PUBLISHABLE_KEY
    || "pk_test_unused",
});

/**
 * Resolve a user's primary email + locale from their Clerk record.
 * Mirrors automation/newsletter/subscribers.py::_parse_clerk_user.
 */
function userToContact(u) {
  if (!u || typeof u !== "object") return null;
  const publicMd = u.publicMetadata || {};
  const plan = typeof publicMd.plan === "string" ? publicMd.plan : null;
  if (!PRO_PLANS.has(plan)) return null;

  const addresses = u.emailAddresses || [];
  const primaryId = u.primaryEmailAddressId;
  let email = "";
  if (primaryId && Array.isArray(addresses)) {
    for (const a of addresses) {
      if (a && a.id === primaryId) {
        email = a.emailAddress || "";
        break;
      }
    }
  }
  if (!email && Array.isArray(addresses)) {
    for (const a of addresses) {
      email = (a && a.emailAddress) || "";
      if (email) break;
    }
  }
  email = typeof email === "string" ? email.trim().toLowerCase() : "";
  if (!email || !email.includes("@")) return null;

  // Locale: Pulpo stores it on publicMetadata.profile.language (PR-NL-7a)
  // or publicMetadata.language (post-P3 rename). Default "en".
  const profile = (publicMd.profile && typeof publicMd.profile === "object") ? publicMd.profile : {};
  const rawLocale = profile.language || publicMd.language || "en";
  const locale = (rawLocale === "es") ? "es" : "en";

  return {
    id: u.id,
    email,
    locale,
    plan,
  };
}

async function listAllProUsers() {
  const out = [];
  let offset = 0;
  for (let page = 0; page < 50; page++) {
    const { data: users } = await clerk.users.getUserList({
      limit: CLERK_PAGE_SIZE,
      offset,
    });
    if (!Array.isArray(users) || users.length === 0) break;
    for (const u of users) {
      const c = userToContact(u);
      if (c) out.push(c);
    }
    if (users.length < CLERK_PAGE_SIZE) break;
    offset += CLERK_PAGE_SIZE;
  }
  return out;
}

async function main() {
  console.log(`[backfill] mode=${DRY_RUN ? "DRY-RUN" : "LIVE"}`);
  const contacts = await listAllProUsers();
  console.log(`[backfill] found ${contacts.length} Pro/Agency users in Clerk`);

  if (contacts.length === 0) {
    console.log("[backfill] nothing to do; exit");
    return;
  }

  if (DRY_RUN) {
    console.log("[backfill] would enroll:");
    for (const c of contacts) {
      console.log(`  ${c.email}  locale=${c.locale}  plan=${c.plan}`);
    }
    console.log("[backfill] dry-run complete; no Resend writes performed");
    return;
  }

  let enrolled = 0;
  let dedup = 0;
  let failed = 0;
  for (const c of contacts) {
    const r = await enrollPaidUserInAudience({
      email: c.email,
      locale: c.locale,
      source: "scripts.backfill_resend_audience",
    });
    if (r.ok) {
      if (r.dedup) {
        dedup += 1;
        console.log(`  ↻ dedup     ${c.email}`);
      } else {
        enrolled += 1;
        console.log(`  ✓ enrolled  ${c.email}`);
      }
    } else {
      failed += 1;
      console.log(`  ✗ failed    ${c.email}  reason=${r.reason || "unknown"}`);
    }
  }
  console.log(`[backfill] done: enrolled=${enrolled} dedup=${dedup} failed=${failed} total=${contacts.length}`);
}

main().catch((err) => {
  console.error("[backfill] fatal:", err);
  process.exit(1);
});
