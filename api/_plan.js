// Backend twin of web/app/lib/founder-emails.ts.
//
// Reads FOUNDER_EMAILS (or VITE_FOUNDER_EMAILS as a fallback — Vercel
// exposes Vite-prefixed env vars to serverless functions too, same
// pattern as api/_clerk.js's publishable-key fallback). Comma list
// of addresses that should be treated as Pro across every server-side
// gate (saves cap, billing portal access, off-market source URLs).
//
// One source of truth on the backend; one on the frontend; same env
// var feeds both so they can't drift.

function readFounderEmails() {
  const raw = process.env.FOUNDER_EMAILS || process.env.VITE_FOUNDER_EMAILS || "";
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

// Evaluated once at module load — env vars are static for the
// lifetime of the serverless function instance.
const FOUNDER_EMAILS = readFounderEmails();

function isFounderEmail(email) {
  if (!email) return false;
  return FOUNDER_EMAILS.has(String(email).toLowerCase());
}

// Resolve the effective plan for a Clerk user object (as returned by
// `clerkClient().users.getUser(userId)`). The Stripe webhook is the
// canonical source — it writes publicMetadata.plan on checkout /
// subscription state changes. The founder allowlist is a manual
// override that promotes specific addresses to "pro" without going
// through Stripe (used for founders / team / comped accounts).
//
// Never demotes: "agency" stays "agency", a webhook-set "pro" stays
// "pro" even if the email isn't on the allowlist.
function effectivePlan(clerkUser) {
  if (!clerkUser) return "free";
  const raw = clerkUser.publicMetadata && clerkUser.publicMetadata.plan;
  if (raw === "pro" || raw === "agency") return raw;
  const emailObj = clerkUser.primaryEmailAddress;
  const email = emailObj && emailObj.emailAddress ? emailObj.emailAddress : null;
  if (isFounderEmail(email)) return "pro";
  return "free";
}

module.exports = { effectivePlan, isFounderEmail };
