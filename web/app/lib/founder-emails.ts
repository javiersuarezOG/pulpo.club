// Founder / team override for the Pro plan gate.
//
// Reads VITE_FOUNDER_EMAILS at build time — a comma-separated list of
// addresses that should be treated as Pro across every gate in the app
// (display caps, CTA routing, header identity) without going through
// Stripe checkout. Mirrors api/_plan.js on the backend so server-side
// authorization (saves cap, billing portal access, off-market source
// URLs) honors the same allowlist.
//
// Not a secret — the list ships in the JS bundle and is visible to any
// browser. That's fine: knowing which addresses are founders doesn't
// grant access; the gate still requires being signed in as that user.

const RAW = (import.meta.env.VITE_FOUNDER_EMAILS as string | undefined) || "";

const FOUNDER_EMAILS: ReadonlySet<string> = new Set(
  RAW.split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean),
);

export function isFounderEmail(email: string | null | undefined): boolean {
  if (!email) return false;
  return FOUNDER_EMAILS.has(email.toLowerCase());
}

// Wrap any object that carries `{email, plan}` and promote plan to
// "pro" when the email matches. Used at the two hydration sites
// (clerk-bundle.jsx for Clerk sessions, app.jsx for legacy
// localStorage seeds) so every downstream `app.user.plan` reader sees
// the override transparently. Never demotes — agency stays agency,
// real pro stays pro.
export function applyFounderPlan<U extends { email?: string | null; plan?: string | null } | null | undefined>(
  user: U,
): U {
  if (!user || !user.email) return user;
  if (user.plan === "pro" || user.plan === "agency") return user;
  if (!isFounderEmail(user.email)) return user;
  return { ...user, plan: "pro" } as U;
}
