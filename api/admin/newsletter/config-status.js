// GET /api/admin/newsletter/config-status
//
// Live env probe for the /admin/newsletter console's "Config &
// connections" strip. Returns one row per server-side dependency the
// newsletter tool needs, each with a presence-only status — never the
// secret value itself, only whether it's set.
//
// Why this exists: before this endpoint, a missing secret (an empty
// GITHUB_DISPATCH_TOKEN, a dropped Resend key, dry-run left on) was
// invisible until an operator clicked Send and the action failed with a
// cryptic code. The console reads this on mount and shows the broken
// dependency as a red row up front, so "why won't it send" is answered
// before the click, not after.
//
// Read path mirrors ./health.js: auth-light (no secret material in the
// response — only "ok" / "missing" booleans + non-sensitive identifiers
// like the dispatch repo/ref and the send mode), rate-limited.
//
// Status vocabulary per row:
//   ok   — dependency is configured and ready
//   warn — present but in a non-default / attention state (dry-run on)
//   bad  — required for a core send path and missing
//
// `blocks` names, in plain English, what stops working when the row is
// not ok — so the operator can map a red row to the button it breaks.

const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");

const limiter = makeRateLimiter({
  windowMs: 60 * 1000,
  maxAttempts: 30,
  name: "admin_newsletter_config_status",
});

function present(name) {
  return (process.env[name] || "").trim().length > 0;
}

// Names of the env vars in `names` that are unset/blank. Lets a red row
// say exactly which var to set ("POSTHOG_PROJECT_ID missing") instead of
// a vague "read keys missing" the operator then has to go decode.
function missingVars(...names) {
  return names.filter((n) => !present(n));
}

// "X missing" / "X + Y missing" — the actionable tail of a config row.
function missingDetail(...names) {
  const missing = missingVars(...names);
  if (missing.length === 0) return null;
  return `${missing.join(" + ")} missing`;
}

// PULPO_NEWSLETTER_DRY_RUN gates real sends in the Python pipeline. It's
// "on" for any truthy-ish value; anything else (unset / "0" / "false")
// means live sends go out. Mirror the pipeline's own parsing so the
// console never disagrees with what actually happens.
function dryRunOn() {
  const v = (process.env.PULPO_NEWSLETTER_DRY_RUN || "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

function logApi(name, fields) {
  const parts = ["[api]", name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    logApi("admin.newsletter_config_status", { status: 429, ms: Date.now() - t0 });
    return send429(res, rl, "admin_newsletter_config_status");
  }

  const githubOk = present("GITHUB_DISPATCH_TOKEN");
  // Sender address (RESEND_FROM_EMAIL) is required for any real delivery —
  // send.send_issue returns missing_from_email without it. Folded into the
  // Resend readiness so the console can't show green while the From header
  // is unset (Codex: "admin ready checks omit sender address").
  const resendOk = present("RESEND_API_KEY") && present("RESEND_AUDIENCE_ID") && present("RESEND_FROM_EMAIL");
  // Unsubscribe integrity — the salt that makes the `r=` lookup match on
  // Vercel + the secret that signs the one-click token. A live send now
  // FAILS CLOSED without the salt (P0-1); without the secret the token
  // can't verify. Either missing = broken/forgeable unsubscribe (CAN-SPAM).
  const unsubOk = present("PULPO_NEWSLETTER_SALT") && present("PULPO_UNSUBSCRIBE_SECRET");
  const clerkOk = present("CLERK_SECRET_KEY");
  const posthogOk = present("POSTHOG_PERSONAL_API_KEY") && present("POSTHOG_PROJECT_ID");
  const internalOk = present("PULPO_INTERNAL_TOKEN");
  const dry = dryRunOn();

  // Non-secret identifiers are safe to echo so the operator can confirm
  // the dispatch is pointed at the right repo/ref.
  const dispatchRepo = (process.env.GITHUB_DISPATCH_REPO || "javiersuarezOG/pulpo.club").trim();
  const dispatchRef = (process.env.GITHUB_DISPATCH_REF || "main").trim();

  const connections = [
    {
      id: "github_dispatch",
      label: "GitHub dispatch",
      status: githubOk ? "ok" : "bad",
      detail: githubOk ? `${dispatchRepo} · ${dispatchRef}` : missingDetail("GITHUB_DISPATCH_TOKEN"),
      blocks: "Weekly test-sends + Send-to-everyone (workflow dispatch)",
    },
    {
      id: "resend",
      label: "Resend",
      status: resendOk ? "ok" : "bad",
      detail: resendOk ? "API key + audience + sender set" : missingDetail("RESEND_API_KEY", "RESEND_AUDIENCE_ID", "RESEND_FROM_EMAIL"),
      blocks: "All real email delivery + live audience count",
    },
    {
      id: "unsubscribe",
      label: "Unsubscribe links",
      status: unsubOk ? "ok" : "bad",
      detail: unsubOk ? "salt + signing secret set" : missingDetail("PULPO_NEWSLETTER_SALT", "PULPO_UNSUBSCRIBE_SECRET"),
      blocks: "Working unsubscribe links + one-click List-Unsubscribe (live weekly send fails closed without the salt)",
    },
    {
      id: "clerk",
      label: "Clerk",
      status: clerkOk ? "ok" : "bad",
      detail: clerkOk ? "connected" : missingDetail("CLERK_SECRET_KEY"),
      blocks: "Pro audience count + Pro welcome test-sends",
    },
    {
      id: "internal_welcome",
      label: "Welcome dispatcher",
      status: internalOk ? "ok" : "warn",
      detail: internalOk ? "internal token set" : missingDetail("PULPO_INTERNAL_TOKEN"),
      blocks: "Pro / Free welcome + welcome-back test-sends",
    },
    {
      id: "posthog_read",
      label: "PostHog read",
      status: posthogOk ? "ok" : "warn",
      // Names the exact missing var (personal API key vs numeric project
      // id) — the two are different credentials from the POSTHOG_PROJECT_TOKEN
      // the rest of the app uses to WRITE events, so "read keys missing"
      // was easy to misread as "PostHog is down" when ingest works fine.
      detail: posthogOk ? "connected" : missingDetail("POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID"),
      blocks: "Deliverability health + cross-device activity log (read-only; ingest is unaffected)",
    },
    {
      id: "send_mode",
      label: "Send mode",
      status: dry ? "warn" : "ok",
      detail: dry ? "DRY-RUN — no live mail leaves the building" : "LIVE — real email goes out",
      blocks: dry ? "Real delivery (test-sends render but don't send)" : null,
    },
  ];

  const allReady = connections.every((c) => c.status === "ok");
  logApi("admin.newsletter_config_status", {
    status: 200, ms: Date.now() - t0,
    github: githubOk ? "ok" : "missing",
    resend: resendOk ? "ok" : "missing",
    clerk: clerkOk ? "ok" : "missing",
    posthog: posthogOk ? "ok" : "missing",
    dry_run: dry ? "on" : "off",
  });

  // Cache briefly — env doesn't change between deploys, but a short TTL
  // keeps the strip fresh after a Vercel env edit + redeploy.
  res.setHeader("Cache-Control", "no-store");
  return res.status(200).json({ all_ready: allReady, connections });
};
