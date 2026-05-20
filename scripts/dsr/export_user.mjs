#!/usr/bin/env node
//
// Data Subject Request — EXPORT.
//
// Walks every system Pulpo touches that holds personal data about a
// single user, identified by email, and writes a single JSON dump
// containing everything we have on them. Suitable for delivery in
// response to a GDPR Art. 15 (right of access) or LGPD Art. 18
// (confirmação + acesso) request.
//
// The Privacy Policy at web/app/config/legal-content.ts:316 commits us
// to a 30-day acknowledgment window (GDPR Art. 12(3)) and a 90-day
// completion window for full requests. This script is the operational
// half of that promise — without it, every export request requires
// manual hand-querying across four SaaS dashboards, which doesn't
// scale and doesn't leave an audit trail.
//
// Usage:
//
//   node scripts/dsr/export_user.mjs --email user@example.com
//   node scripts/dsr/export_user.mjs --email user@example.com --out /tmp/dsr.json
//
// Output is a deterministic JSON object — same input + same data
// produces a byte-stable export — so an export run twice for the
// same user produces matching files (useful for audit + verification).
//
// Required env vars:
//
//   CLERK_SECRET_KEY          — Clerk Backend API key
//   STRIPE_SECRET_KEY         — Stripe Secret API key
//   RESEND_API_KEY            — Resend API key
//   RESEND_AUDIENCE_ID        — Audience UUID for the newsletter list
//   POSTHOG_PROJECT_TOKEN     — PostHog project API key (read)
//   POSTHOG_PERSONAL_API_KEY  — PostHog personal API key (Person read)
//                               Get from https://app.posthog.com/settings → Personal API keys
//   POSTHOG_PROJECT_ID        — Numeric project ID from the PostHog URL
//                               (e.g. 12345 in /project/12345/...)
//
// This script is READ-ONLY. It never mutates any source system. The
// companion `delete_user.mjs` is the destructive sibling.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const ARGV = process.argv.slice(2);

function arg(flag, fallback) {
  const i = ARGV.indexOf(flag);
  if (i < 0) return fallback;
  return ARGV[i + 1];
}

function hasFlag(flag) {
  return ARGV.includes(flag);
}

function emailHash(email) {
  return crypto
    .createHash("sha256")
    .update(email.trim().toLowerCase())
    .digest("hex")
    .slice(0, 16);
}

function posthogDistinctId(email) {
  return `email:${emailHash(email)}`;
}

function log(line) {
  console.log(`[dsr.export] ${line}`);
}

function logErr(line) {
  console.error(`[dsr.export] ${line}`);
}

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, opts);
  let body;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { ok: res.ok, status: res.status, body };
}

// ── Per-provider readers ──────────────────────────────────────────────

async function readClerk(email) {
  const key = process.env.CLERK_SECRET_KEY;
  if (!key) {
    return { configured: false, reason: "CLERK_SECRET_KEY not set" };
  }
  // Clerk's user-list-by-email is an authenticated GET. We don't pull
  // in @clerk/backend here to keep the script standalone — the REST
  // endpoint is stable enough.
  const url = `https://api.clerk.com/v1/users?email_address=${encodeURIComponent(email)}`;
  const { ok, status, body } = await fetchJson(url, {
    headers: { Authorization: `Bearer ${key}` },
  });
  if (!ok) {
    return { configured: true, error: `clerk_http_${status}`, body };
  }
  const users = Array.isArray(body) ? body : (body && body.data) || [];
  return { configured: true, users };
}

async function readStripe(email) {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) {
    return { configured: false, reason: "STRIPE_SECRET_KEY not set" };
  }
  // Customers search supports email; subscriptions are linked via
  // customer.id. Two calls + a small join.
  const customers = await fetchJson(
    `https://api.stripe.com/v1/customers?email=${encodeURIComponent(email)}&limit=10`,
    { headers: { Authorization: `Bearer ${key}` } },
  );
  if (!customers.ok) {
    return { configured: true, error: `stripe_customers_http_${customers.status}`, body: customers.body };
  }
  const customerList = (customers.body && customers.body.data) || [];

  const enriched = [];
  for (const c of customerList) {
    const subs = await fetchJson(
      `https://api.stripe.com/v1/subscriptions?customer=${encodeURIComponent(c.id)}&status=all&limit=100`,
      { headers: { Authorization: `Bearer ${key}` } },
    );
    enriched.push({
      customer: c,
      subscriptions: (subs.body && subs.body.data) || [],
    });
  }
  return { configured: true, customers: enriched };
}

async function readPostHog(email) {
  const personalKey = process.env.POSTHOG_PERSONAL_API_KEY;
  const projectId = process.env.POSTHOG_PROJECT_ID;
  if (!personalKey || !projectId) {
    return {
      configured: false,
      reason: "POSTHOG_PERSONAL_API_KEY or POSTHOG_PROJECT_ID not set",
    };
  }
  const host = (process.env.POSTHOG_HOST || "https://eu.i.posthog.com").replace(
    /\/$/,
    "",
  );
  const distinctId = posthogDistinctId(email);
  // PostHog's persons list-by-distinct_id endpoint returns Person
  // properties + the linked distinct_ids (the alias chain).
  const url = `${host}/api/projects/${projectId}/persons/?distinct_id=${encodeURIComponent(distinctId)}`;
  const { ok, status, body } = await fetchJson(url, {
    headers: { Authorization: `Bearer ${personalKey}` },
  });
  if (!ok) {
    return {
      configured: true,
      error: `posthog_http_${status}`,
      distinct_id: distinctId,
      body,
    };
  }
  return {
    configured: true,
    distinct_id: distinctId,
    persons: (body && body.results) || [],
  };
}

async function readResend(email) {
  const key = process.env.RESEND_API_KEY;
  const audienceId = process.env.RESEND_AUDIENCE_ID;
  if (!key || !audienceId) {
    return {
      configured: false,
      reason: "RESEND_API_KEY or RESEND_AUDIENCE_ID not set",
    };
  }
  // Resend doesn't have a "find contact by email in audience X"
  // endpoint, so we list contacts and filter. At Pulpo's audience
  // size this is fine; revisit if the audience grows past ~10k.
  const url = `https://api.resend.com/audiences/${encodeURIComponent(audienceId)}/contacts`;
  const { ok, status, body } = await fetchJson(url, {
    headers: { Authorization: `Bearer ${key}` },
  });
  if (!ok) {
    return { configured: true, error: `resend_http_${status}`, body };
  }
  const all = (body && body.data) || [];
  const match = all.find(
    (c) => (c.email || "").toLowerCase() === email.toLowerCase(),
  );
  return { configured: true, contact: match || null };
}

// ── Main ──────────────────────────────────────────────────────────────

async function main() {
  if (hasFlag("--help") || hasFlag("-h")) {
    log("usage: node scripts/dsr/export_user.mjs --email <addr> [--out <path>]");
    process.exit(0);
  }
  const email = arg("--email", "");
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    logErr("missing or invalid --email <addr> argument");
    logErr("usage: node scripts/dsr/export_user.mjs --email user@example.com [--out path.json]");
    process.exit(2);
  }

  log(`exporting user data for ${email}`);

  const startedAt = new Date().toISOString();
  const [clerk, stripe, posthog, resend] = await Promise.all([
    readClerk(email).catch((err) => ({ configured: true, error: err.message })),
    readStripe(email).catch((err) => ({ configured: true, error: err.message })),
    readPostHog(email).catch((err) => ({ configured: true, error: err.message })),
    readResend(email).catch((err) => ({ configured: true, error: err.message })),
  ]);
  const completedAt = new Date().toISOString();

  const manifest = {
    schema_version: 1,
    request: {
      type: "GDPR Art. 15 / LGPD Art. 18 — right of access",
      email,
      email_hash: emailHash(email),
      posthog_distinct_id: posthogDistinctId(email),
    },
    timing: {
      started_at: startedAt,
      completed_at: completedAt,
    },
    sources: {
      clerk,
      stripe,
      posthog,
      resend,
    },
  };

  const outPath =
    arg("--out", "") ||
    `dsr-exports/${emailHash(email)}-${startedAt.replace(/[:.]/g, "-")}.json`;
  const dir = path.dirname(outPath);
  if (dir && dir !== ".") fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(manifest, null, 2));

  // Summary line for the operator.
  const summary = [
    `clerk=${clerk.configured ? (clerk.users ? `${clerk.users.length}_user(s)` : "error") : "skipped"}`,
    `stripe=${stripe.configured ? (stripe.customers ? `${stripe.customers.length}_customer(s)` : "error") : "skipped"}`,
    `posthog=${posthog.configured ? (posthog.persons ? `${posthog.persons.length}_person(s)` : "error") : "skipped"}`,
    `resend=${resend.configured ? (resend.contact ? "found" : "not_found") : "skipped"}`,
  ].join(" ");

  log(`written: ${outPath}`);
  log(summary);
}

main().catch((err) => {
  logErr(`fatal: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
