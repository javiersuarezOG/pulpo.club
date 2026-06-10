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
  const resendOk = present("RESEND_API_KEY") && present("RESEND_AUDIENCE_ID");
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
      detail: githubOk ? `${dispatchRepo} · ${dispatchRef}` : "GITHUB_DISPATCH_TOKEN missing",
      blocks: "Weekly test-sends + Send-to-everyone (workflow dispatch)",
    },
    {
      id: "resend",
      label: "Resend",
      status: resendOk ? "ok" : "bad",
      detail: resendOk ? "API key + audience set" : "RESEND_API_KEY / RESEND_AUDIENCE_ID missing",
      blocks: "All real email delivery + live audience count",
    },
    {
      id: "clerk",
      label: "Clerk",
      status: clerkOk ? "ok" : "bad",
      detail: clerkOk ? "connected" : "CLERK_SECRET_KEY missing",
      blocks: "Pro audience count + Pro welcome test-sends",
    },
    {
      id: "internal_welcome",
      label: "Welcome dispatcher",
      status: internalOk ? "ok" : "warn",
      detail: internalOk ? "internal token set" : "PULPO_INTERNAL_TOKEN missing",
      blocks: "Pro / Free welcome + welcome-back test-sends",
    },
    {
      id: "posthog_read",
      label: "PostHog read",
      status: posthogOk ? "ok" : "warn",
      detail: posthogOk ? "connected" : "read keys missing",
      blocks: "Deliverability health + cross-device activity log",
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
