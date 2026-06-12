// Email capture → Free membership. Single POST helper shared by the home
// hero form and the EmailCaptureModal so both submit the same way and both
// turn the visitor into a Free member (email-first funnel).

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
  try {
    const r = await fetch("/api/newsletter", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: value, source: opts.source, locale: opts.locale }),
    });
    const body = await r.json().catch(() => ({} as Record<string, unknown>));
    if (r.ok) return { kind: body.resubscribed ? "already" : "success" };
    if (r.status === 429) return { kind: "rate_limited" };
    if (body && body.error === "invalid_email") return { kind: "invalid" };
    return { kind: "error" };
  } catch {
    return { kind: "error" };
  }
}
