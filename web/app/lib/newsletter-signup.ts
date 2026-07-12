// Email capture → Free membership. Single POST helper shared by the home
// hero form and the EmailCaptureModal so both submit the same way and both
// turn the visitor into a Free member (email-first funnel).

import { captureCampaignParams } from "./campaign";

export const NL_EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export type SubscribeResult =
  | { kind: "success" }      // new contact created
  | { kind: "already" }      // re-subscribed / already on the list
  | { kind: "invalid" }      // bad email
  | { kind: "rate_limited" }
  | { kind: "error" };

// POSTs the email to /api/newsletter (Resend audience + free welcome).
// Pure transport: never throws, returns a discriminated result. The caller
// decides what client state to set (e.g. app.becomeFreeMember).
export async function subscribeEmail(
  email: string,
  opts: { source: string; locale: string },
): Promise<SubscribeResult> {
  const value = (email || "").trim();
  if (!NL_EMAIL_RE.test(value)) return { kind: "invalid" };
  // Campaign attribution: forward the session's UTMs (current URL or the
  // sessionStorage fallback — the same source of truth /start uses) so the
  // server can fire the newsletter.signup funnel event + stamp first-touch
  // acquisition props on the PostHog Person. `{}` for direct traffic.
  const utms = captureCampaignParams().utms;
  try {
    const r = await fetch("/api/newsletter", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: value, source: opts.source, locale: opts.locale, utms }),
    });
    const body = await r.json().catch(() => ({} as Record<string, unknown>));
    // "already" covers BOTH server signals: `resubscribed` (was unsubscribed,
    // welcome-back sent) AND `already_subscribed` (still active, idempotent
    // no-op). Reading only `resubscribed` was the gap that let an already-
    // active subscriber be classed as `success` on the default hero
    // (AccessBlock) + EmailCaptureModal → the QA bug-3 octopus celebration
    // replayed there even after the inline-EmailCapture fix. Both callers pass
    // this through to becomeFreeMember({returning}) which suppresses the reveal.
    if (r.ok) return { kind: (body.resubscribed || body.already_subscribed) ? "already" : "success" };
    if (r.status === 429) return { kind: "rate_limited" };
    if (body && body.error === "invalid_email") return { kind: "invalid" };
    return { kind: "error" };
  } catch {
    return { kind: "error" };
  }
}
