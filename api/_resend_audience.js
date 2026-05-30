// Shared Resend audience-membership helper for Pulpo's Pro/Agency
// newsletter audience (the audience identified by RESEND_AUDIENCE_ID).
//
// Pulpo's product model: the personalised weekly newsletter is a Pro
// feature. Audience membership therefore tracks Pro/Agency entitlement:
//
//   • Pro/Agency upgrade        →  enrollPaidUserInAudience()
//                                    (sets unsubscribed=false)
//   • Subscription canceled     →  unsubscribeOnPlanLoss()
//                                    (sets unsubscribed=true, preserves
//                                     the contact for analytics +
//                                     reversibility if they re-upgrade)
//   • Footer Unsubscribe link   →  api/unsubscribe.js (unchanged;
//                                    operator-initiated)
//
// Pre-2026-05-30 the only write path into the audience was the
// homepage "Get the 10 best" CTA (api/newsletter.js). Stripe upgrades
// silently bypassed Resend, so Pro users were entitled in Clerk but
// invisible to the audience-count + send pipelines. Backfill +
// webhook wire shipped together in the same PR; this helper is the
// shared write surface.
//
// All calls are BEST-EFFORT. A Resend outage must NEVER block the
// upstream action (payment, account state). Failures log + return a
// shape so callers can record telemetry without throwing.

const RESEND_BASE = "https://api.resend.com";

function _log(fields) {
  const parts = ["[api]", "_resend_audience"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

function _config() {
  return {
    apiKey: process.env.RESEND_API_KEY || "",
    audienceId: process.env.RESEND_AUDIENCE_ID || "",
  };
}

/**
 * Add the email to the Pulpo Pro newsletter audience.
 * Idempotent: a Resend "already exists" response flips unsubscribed=false
 * (covers the re-upgrade case where a former Pro who unsubscribed comes back).
 *
 * @param {object} args
 * @param {string} args.email              recipient email (required)
 * @param {string} [args.locale="en"]      "en" | "es" — encoded into first_name per Pulpo's locale side-channel
 * @param {string} [args.source]           free-form tag for the log line — e.g. "stripe.checkout.new_user"
 * @returns {Promise<{ok: boolean, reason?: string, dedup?: boolean}>}
 */
async function enrollPaidUserInAudience({ email, locale = "en", source = "unknown" } = {}) {
  const { apiKey, audienceId } = _config();
  if (!apiKey || !audienceId) {
    _log({ op: "enroll", result: "skip", reason: "missing_config", source });
    return { ok: false, reason: "missing_config" };
  }
  if (!email || typeof email !== "string" || !email.includes("@")) {
    _log({ op: "enroll", result: "skip", reason: "invalid_email", source });
    return { ok: false, reason: "invalid_email" };
  }
  const safeLocale = (locale === "es" || locale === "en") ? locale : "en";

  try {
    const r = await fetch(`${RESEND_BASE}/audiences/${audienceId}/contacts`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        email,
        // Pulpo's locale side-channel: first_name carries "pulpo-locale:<lc>"
        // (see api/newsletter.js for the original site). The newsletter
        // pipeline parses this in automation/newsletter/subscribers.py to
        // pick the recipient's locale.
        first_name: `pulpo-locale:${safeLocale}`,
        unsubscribed: false,
      }),
    });
    const body = await r.json().catch(() => ({}));
    if (r.ok) {
      _log({ op: "enroll", result: "ok", email, source });
      return { ok: true };
    }
    // Resend returns 422 + validation_error name when the contact already
    // exists. Treat as success + flip unsubscribed=false in case they
    // previously unsubscribed but are re-upgrading. The PATCH lookup-by-
    // email keeps this single round-trip.
    const msg = (body && body.message) || "";
    if (r.status === 422 && /already exists|duplicate|already subscribed/i.test(msg)) {
      _log({ op: "enroll", result: "dedup", email, source });
      const patch = await _setUnsubscribed({ email, unsubscribed: false, source });
      return { ok: patch.ok, dedup: true, reason: patch.reason };
    }
    _log({
      op: "enroll", result: "fail",
      email, status: r.status, source,
      body_snippet: JSON.stringify(body).slice(0, 200),
    });
    return { ok: false, reason: `http_${r.status}` };
  } catch (err) {
    _log({ op: "enroll", result: "error", email, source, error: err && err.message });
    return { ok: false, reason: "fetch_error" };
  }
}

/**
 * Flip a contact's unsubscribed flag to true on Pro→Free transition.
 * Preserves the contact (history, analytics) and is reversible — if
 * the user re-upgrades, enrollPaidUserInAudience() flips it back.
 *
 * Deliberately NOT a DELETE: deletion loses send-history attribution
 * and breaks the "re-upgrade restores newsletter" round-trip.
 */
async function unsubscribeOnPlanLoss({ email, source = "unknown" } = {}) {
  return _setUnsubscribed({ email, unsubscribed: true, source });
}

async function _setUnsubscribed({ email, unsubscribed, source }) {
  const { apiKey, audienceId } = _config();
  if (!apiKey || !audienceId) {
    _log({ op: "set_unsubscribed", result: "skip", reason: "missing_config", source });
    return { ok: false, reason: "missing_config" };
  }
  if (!email || typeof email !== "string" || !email.includes("@")) {
    _log({ op: "set_unsubscribed", result: "skip", reason: "invalid_email", source });
    return { ok: false, reason: "invalid_email" };
  }
  try {
    const r = await fetch(
      `${RESEND_BASE}/audiences/${audienceId}/contacts/${encodeURIComponent(email)}`,
      {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ unsubscribed: !!unsubscribed }),
      },
    );
    if (r.ok) {
      _log({ op: "set_unsubscribed", result: "ok", email, value: !!unsubscribed, source });
      return { ok: true };
    }
    // 404: contact doesn't exist in the audience. For unsubscribe path
    // that's fine (nothing to flip); for enroll-dedup that shouldn't
    // happen since enroll just got back "already exists".
    if (r.status === 404) {
      _log({ op: "set_unsubscribed", result: "not_found", email, source });
      return { ok: true, reason: "not_in_audience" };
    }
    _log({ op: "set_unsubscribed", result: "fail", email, status: r.status, source });
    return { ok: false, reason: `http_${r.status}` };
  } catch (err) {
    _log({ op: "set_unsubscribed", result: "error", email, source, error: err && err.message });
    return { ok: false, reason: "fetch_error" };
  }
}

module.exports = {
  enrollPaidUserInAudience,
  unsubscribeOnPlanLoss,
};
