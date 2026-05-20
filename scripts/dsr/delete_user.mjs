#!/usr/bin/env node
//
// Data Subject Request — DELETE.
//
// Walks every system Pulpo touches that holds personal data about a
// single user, identified by email, and removes them. Suitable for
// executing a GDPR Art. 17 (right to erasure) or LGPD Art. 18 V
// (eliminação) request.
//
// The Privacy Policy at web/app/config/legal-content.ts:298 commits us
// to wiping account data within 90 days of the deletion request. This
// script is the operational half of that promise — without it, every
// erasure request requires manual clicking across four SaaS
// dashboards, which doesn't scale and leaves no audit trail.
//
// SAFETY MODEL
//
// The script defaults to DRY-RUN mode. In dry-run it reads what would
// be deleted, prints a manifest, and exits. No mutations. To actually
// delete, pass --apply explicitly. There is no --no-dry-run inverse —
// the destructive verb is always the explicit, opt-in flag.
//
// In --apply mode, the script:
//   - Cancels Stripe subscriptions (status → canceled), then deletes
//     the Stripe customer record. The legal-retention exception
//     (Dutch belastingdienst / 7-year billing record obligation per
//     legal-content.ts:299) means Stripe customer + payment records
//     persist as-is in Stripe's own DPA-bound retention. We delete
//     OUR linked customer/customer.metadata layer; Stripe keeps the
//     invoice trail to satisfy the tax authority. This matches the
//     Privacy Policy's "(subject to legal retention)" qualifier on
//     GDPR Art. 17.
//   - Deletes the Clerk user (revokes sessions + invitations + saves).
//   - Deletes the PostHog Person + all associated events.
//   - Removes the Resend audience contact.
//
// Always writes an audit manifest to dsr-deletions/<hash>-<ts>.json,
// EVEN IN DRY-RUN, so we have proof of what was reviewed.
//
// Usage:
//
//   # Dry-run (default — always do this first):
//   node scripts/dsr/delete_user.mjs --email user@example.com
//
//   # Apply the deletion (destructive — second call after reviewing dry-run):
//   node scripts/dsr/delete_user.mjs --email user@example.com --apply
//
// Required env vars: see export_user.mjs (same set).

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
  console.log(`[dsr.delete] ${line}`);
}

function logErr(line) {
  console.error(`[dsr.delete] ${line}`);
}

async function callJson(url, opts = {}) {
  const res = await fetch(url, opts);
  let body;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { ok: res.ok, status: res.status, body };
}

// ── Per-provider deleters (no-op in dry-run) ──────────────────────────

async function deleteClerk(email, { apply }) {
  const key = process.env.CLERK_SECRET_KEY;
  if (!key) return { configured: false, reason: "CLERK_SECRET_KEY not set" };
  const list = await callJson(
    `https://api.clerk.com/v1/users?email_address=${encodeURIComponent(email)}`,
    { headers: { Authorization: `Bearer ${key}` } },
  );
  if (!list.ok) {
    return { configured: true, error: `clerk_list_http_${list.status}`, body: list.body };
  }
  const users = Array.isArray(list.body) ? list.body : (list.body && list.body.data) || [];
  if (!users.length) return { configured: true, applied: false, found: 0, deleted: [] };
  if (!apply) {
    return {
      configured: true,
      applied: false,
      found: users.length,
      would_delete: users.map((u) => u.id),
    };
  }
  const deleted = [];
  for (const u of users) {
    const r = await callJson(`https://api.clerk.com/v1/users/${u.id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${key}` },
    });
    deleted.push({ id: u.id, ok: r.ok, status: r.status });
  }
  return { configured: true, applied: true, found: users.length, deleted };
}

async function deleteStripe(email, { apply }) {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) return { configured: false, reason: "STRIPE_SECRET_KEY not set" };
  const list = await callJson(
    `https://api.stripe.com/v1/customers?email=${encodeURIComponent(email)}&limit=10`,
    { headers: { Authorization: `Bearer ${key}` } },
  );
  if (!list.ok) {
    return { configured: true, error: `stripe_list_http_${list.status}`, body: list.body };
  }
  const customers = (list.body && list.body.data) || [];
  if (!customers.length) return { configured: true, applied: false, found: 0, actions: [] };

  // Discover active subscriptions per customer so the dry-run plan
  // tells the operator what's about to be canceled.
  const plan = [];
  for (const c of customers) {
    const subs = await callJson(
      `https://api.stripe.com/v1/subscriptions?customer=${encodeURIComponent(c.id)}&status=all&limit=100`,
      { headers: { Authorization: `Bearer ${key}` } },
    );
    plan.push({
      customer_id: c.id,
      created: c.created,
      subscription_ids: ((subs.body && subs.body.data) || []).map((s) => s.id),
    });
  }
  if (!apply) {
    return {
      configured: true,
      applied: false,
      found: customers.length,
      would_cancel_and_delete: plan,
      note:
        "Stripe customer + invoice records persist in Stripe's own retention to satisfy " +
        "the 7-year Dutch belastingdienst / VAT obligation (Privacy Policy retention §). " +
        "This script removes our linked customer reference; Stripe keeps the invoice trail.",
    };
  }
  const actions = [];
  for (const entry of plan) {
    for (const subId of entry.subscription_ids) {
      const r = await callJson(`https://api.stripe.com/v1/subscriptions/${subId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${key}` },
      });
      actions.push({ kind: "subscription_canceled", id: subId, ok: r.ok, status: r.status });
    }
    const r = await callJson(`https://api.stripe.com/v1/customers/${entry.customer_id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${key}` },
    });
    actions.push({ kind: "customer_deleted", id: entry.customer_id, ok: r.ok, status: r.status });
  }
  return { configured: true, applied: true, found: customers.length, actions };
}

async function deletePostHog(email, { apply }) {
  const personalKey = process.env.POSTHOG_PERSONAL_API_KEY;
  const projectId = process.env.POSTHOG_PROJECT_ID;
  if (!personalKey || !projectId) {
    return {
      configured: false,
      reason: "POSTHOG_PERSONAL_API_KEY or POSTHOG_PROJECT_ID not set",
    };
  }
  const host = (process.env.POSTHOG_HOST || "https://eu.i.posthog.com").replace(/\/$/, "");
  const distinctId = posthogDistinctId(email);
  const list = await callJson(
    `${host}/api/projects/${projectId}/persons/?distinct_id=${encodeURIComponent(distinctId)}`,
    { headers: { Authorization: `Bearer ${personalKey}` } },
  );
  if (!list.ok) {
    return { configured: true, error: `posthog_list_http_${list.status}`, body: list.body };
  }
  const persons = (list.body && list.body.results) || [];
  if (!persons.length) return { configured: true, applied: false, found: 0, deleted: [] };
  if (!apply) {
    return {
      configured: true,
      applied: false,
      found: persons.length,
      would_delete: persons.map((p) => ({ id: p.id, distinct_ids: p.distinct_ids })),
    };
  }
  // PostHog's person-delete: ?delete_events=true wipes the event row
  // history too. Without it, the Person record vanishes but the raw
  // events remain pseudonymized — which is NOT what GDPR Art. 17
  // requires for a full erasure.
  const deleted = [];
  for (const p of persons) {
    const r = await callJson(
      `${host}/api/projects/${projectId}/persons/${p.id}/?delete_events=true`,
      {
        method: "DELETE",
        headers: { Authorization: `Bearer ${personalKey}` },
      },
    );
    deleted.push({ id: p.id, ok: r.ok, status: r.status });
  }
  return { configured: true, applied: true, found: persons.length, deleted };
}

async function deleteResend(email, { apply }) {
  const key = process.env.RESEND_API_KEY;
  const audienceId = process.env.RESEND_AUDIENCE_ID;
  if (!key || !audienceId) {
    return {
      configured: false,
      reason: "RESEND_API_KEY or RESEND_AUDIENCE_ID not set",
    };
  }
  // Resend deletes by email or by contact ID. By-email is simpler;
  // we don't need the listing step the export script does.
  if (!apply) {
    return {
      configured: true,
      applied: false,
      would_delete: { audience_id: audienceId, email },
    };
  }
  const r = await callJson(
    `https://api.resend.com/audiences/${encodeURIComponent(audienceId)}/contacts/${encodeURIComponent(email)}`,
    { method: "DELETE", headers: { Authorization: `Bearer ${key}` } },
  );
  return {
    configured: true,
    applied: true,
    deleted: { audience_id: audienceId, email, ok: r.ok, status: r.status },
  };
}

// ── Main ──────────────────────────────────────────────────────────────

async function main() {
  if (hasFlag("--help") || hasFlag("-h")) {
    log("usage: node scripts/dsr/delete_user.mjs --email <addr> [--apply] [--out <path>]");
    log("");
    log("  default mode is DRY-RUN. Pass --apply to actually delete.");
    log("  always writes a manifest of what was planned or applied.");
    process.exit(0);
  }
  const email = arg("--email", "");
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    logErr("missing or invalid --email <addr> argument");
    logErr("usage: node scripts/dsr/delete_user.mjs --email user@example.com [--apply] [--out path.json]");
    process.exit(2);
  }

  const apply = hasFlag("--apply");
  const mode = apply ? "APPLY (destructive)" : "DRY-RUN (read-only)";
  log(`mode: ${mode}`);
  log(`target: ${email}`);

  if (apply) {
    log("--apply specified; mutations WILL be made across Clerk + Stripe + PostHog + Resend");
    log("press Ctrl-C within 5 seconds to abort");
    await new Promise((resolve) => setTimeout(resolve, 5_000));
  }

  const startedAt = new Date().toISOString();
  const [clerk, stripe, posthog, resend] = await Promise.all([
    deleteClerk(email, { apply }).catch((err) => ({ configured: true, error: err.message })),
    deleteStripe(email, { apply }).catch((err) => ({ configured: true, error: err.message })),
    deletePostHog(email, { apply }).catch((err) => ({ configured: true, error: err.message })),
    deleteResend(email, { apply }).catch((err) => ({ configured: true, error: err.message })),
  ]);
  const completedAt = new Date().toISOString();

  const manifest = {
    schema_version: 1,
    request: {
      type: "GDPR Art. 17 / LGPD Art. 18 V — right to erasure",
      email,
      email_hash: emailHash(email),
      posthog_distinct_id: posthogDistinctId(email),
    },
    mode: apply ? "applied" : "dry-run",
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

  const outDir = apply ? "dsr-deletions" : "dsr-deletions/dry-runs";
  const outPath =
    arg("--out", "") ||
    `${outDir}/${emailHash(email)}-${startedAt.replace(/[:.]/g, "-")}.json`;
  const dir = path.dirname(outPath);
  if (dir && dir !== ".") fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(manifest, null, 2));

  log(`manifest written: ${outPath}`);
  if (!apply) {
    log("dry-run complete. Review the manifest, then re-run with --apply to execute.");
  } else {
    log("deletion complete. Manifest is the audit trail — retain per Privacy Policy retention §.");
  }
}

main().catch((err) => {
  logErr(`fatal: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
