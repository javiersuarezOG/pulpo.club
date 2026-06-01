// Unit tests for the Pulpo Pro Welcome dispatch helper in
// api/stripe/webhook.js. Covers the pure-ish surface:
//
//   • Idempotency: skip when publicMetadata.welcome_newsletter_sent_at
//     is already set, no GH dispatch fired.
//   • Token missing: skip cleanly, log + PostHog the gap, no fetch.
//   • Happy path: 204 from GitHub → returns "dispatched", fetch is
//     called with the correct workflow + inputs.
//   • GitHub non-204: returns error:github_<status>, telemetry fires.
//   • Fetch throws: returns error:fetch_failed, telemetry fires.
//   • Missing input (no email / no userId): returns skipped:missing_input
//     without touching Clerk or GitHub.
//
// Full webhook integration (Stripe signature → Clerk plan flip →
// welcome dispatch end-to-end) is the Sebas-side preview-URL smoke
// per CLAUDE.md — Stripe sandbox dry-run on a brand-new email.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { dispatchProWelcomeWorkflow } from "../../api/stripe/webhook.js";

function mockClerk({ publicMetadata = {}, getUserThrows = false } = {}) {
  return {
    users: {
      getUser: vi.fn(async () => {
        if (getUserThrows) throw new Error("clerk_unreachable");
        return { publicMetadata };
      }),
    },
  };
}

function mockFetch({ status = 204, body = "", throws = false } = {}) {
  return vi.fn(async () => {
    if (throws) throw new Error("network_unreachable");
    return {
      status,
      text: async () => body,
    };
  });
}

describe("dispatchProWelcomeWorkflow", () => {
  const ORIGINAL_TOKEN = process.env.GITHUB_DISPATCH_TOKEN;

  beforeEach(() => {
    process.env.GITHUB_DISPATCH_TOKEN = "ghp_test_token";
  });
  afterEach(() => {
    if (ORIGINAL_TOKEN === undefined) {
      delete process.env.GITHUB_DISPATCH_TOKEN;
    } else {
      process.env.GITHUB_DISPATCH_TOKEN = ORIGINAL_TOKEN;
    }
  });

  it("skips with already_sent when Clerk publicMetadata has the stamp", async () => {
    const clerk = mockClerk({ publicMetadata: { welcome_newsletter_sent_at: "2026-06-01T10:00:00Z" } });
    const fetchImpl = mockFetch();
    const result = await dispatchProWelcomeWorkflow({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl,
    });
    expect(result).toBe("skipped:already_sent");
    expect(clerk.users.getUser).toHaveBeenCalledOnce();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("dispatches when stamp is missing and GitHub returns 204", async () => {
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = mockFetch({ status: 204 });
    const result = await dispatchProWelcomeWorkflow({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl,
    });
    expect(result).toBe("dispatched");
    expect(fetchImpl).toHaveBeenCalledOnce();
    const [url, opts] = fetchImpl.mock.calls[0];
    expect(url).toContain("pulpo-pro-welcome.yml/dispatches");
    const payload = JSON.parse(opts.body);
    expect(payload.inputs.recipient_email).toBe("user@pulpo.club");
    expect(payload.inputs.send_mode).toBe("yes");
    expect(payload.inputs.source).toBe("stripe");
    expect(payload.inputs.force).toBe("no");
  });

  it("skips with no_github_token when env is missing", async () => {
    delete process.env.GITHUB_DISPATCH_TOKEN;
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = mockFetch();
    const result = await dispatchProWelcomeWorkflow({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl,
    });
    expect(result).toBe("skipped:no_github_token");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("returns error:github_<status> on non-204 dispatch response", async () => {
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = mockFetch({ status: 422, body: "validation failed" });
    const result = await dispatchProWelcomeWorkflow({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl,
    });
    expect(result).toBe("error:github_422");
  });

  it("returns error:fetch_failed when fetch throws", async () => {
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = mockFetch({ throws: true });
    const result = await dispatchProWelcomeWorkflow({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl,
    });
    expect(result).toBe("error:fetch_failed");
  });

  it("skips with missing_input when email is empty", async () => {
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = mockFetch();
    const result = await dispatchProWelcomeWorkflow({
      clerk, clerkUserId: "user_123", email: "",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl,
    });
    expect(result).toBe("skipped:missing_input");
    expect(clerk.users.getUser).not.toHaveBeenCalled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("skips with missing_input when clerkUserId is empty", async () => {
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = mockFetch();
    const result = await dispatchProWelcomeWorkflow({
      clerk, clerkUserId: "", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl,
    });
    expect(result).toBe("skipped:missing_input");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("fail-opens to dispatch when Clerk read throws (better duplicate than silent drop)", async () => {
    const clerk = mockClerk({ getUserThrows: true });
    const fetchImpl = mockFetch({ status: 204 });
    const result = await dispatchProWelcomeWorkflow({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl,
    });
    expect(result).toBe("dispatched");
    expect(fetchImpl).toHaveBeenCalledOnce();
  });
});
