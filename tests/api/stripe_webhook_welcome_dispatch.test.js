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

import {
  callInternalWelcomeSend,
  dispatchProWelcome,
  dispatchProWelcomeWorkflow,
} from "../../api/stripe/webhook.js";

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


// ─────────────────────────────────────────────────────────────────────
// callInternalWelcomeSend — the HTTP wrapper around /api/internal/welcome-send.
// Covers timeout handling, header shape, response parsing.
// ─────────────────────────────────────────────────────────────────────

describe("callInternalWelcomeSend", () => {
  it("POSTs JSON body with Bearer auth + parses response", async () => {
    const fetchImpl = vi.fn(async () => ({
      status: 200,
      json: async () => ({ status: "sent", message_id: "re_abc", latency_ms: 1500 }),
    }));
    const result = await callInternalWelcomeSend({
      baseUrl: "https://pulpo.club",
      token: "internal_token_xyz",
      payload: { email: "user@pulpo.club", source: "stripe", force: false },
      fetchImpl,
    });
    expect(result.ok).toBe(true);
    expect(result.status).toBe(200);
    expect(result.body.status).toBe("sent");
    const [url, opts] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://pulpo.club/api/internal/welcome-send");
    expect(opts.method).toBe("POST");
    expect(opts.headers.Authorization).toBe("Bearer internal_token_xyz");
    expect(opts.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(opts.body)).toEqual({
      email: "user@pulpo.club", source: "stripe", force: false,
    });
  });

  it("returns ok=false on fetch error", async () => {
    const fetchImpl = vi.fn(async () => { throw new Error("ENOTFOUND"); });
    const result = await callInternalWelcomeSend({
      baseUrl: "https://pulpo.club",
      token: "t",
      payload: { email: "u@p.club" },
      fetchImpl,
    });
    expect(result.ok).toBe(false);
    expect(result.reason).toContain("fetch_failed");
  });

  it("returns ok=false with reason=timeout on abort signal", async () => {
    // Simulate a fetch that throws an AbortError when the controller
    // fires. The 50ms timeout should beat the 200ms fake fetch.
    const fetchImpl = vi.fn(async (url, opts) => {
      return new Promise((_, reject) => {
        const onAbort = () => {
          const err = new Error("aborted");
          err.name = "AbortError";
          reject(err);
        };
        if (opts.signal) opts.signal.addEventListener("abort", onAbort);
        // Resolve later than the timeout so the abort wins.
        setTimeout(() => {}, 200);
      });
    });
    const result = await callInternalWelcomeSend({
      baseUrl: "https://pulpo.club",
      token: "t",
      payload: { email: "u@p.club" },
      fetchImpl,
      timeoutMs: 50,
    });
    expect(result.ok).toBe(false);
    expect(result.reason).toBe("timeout");
  });

  it("tolerates a response that isn't JSON-parseable", async () => {
    const fetchImpl = vi.fn(async () => ({
      status: 502,
      json: async () => { throw new Error("invalid JSON"); },
    }));
    const result = await callInternalWelcomeSend({
      baseUrl: "https://pulpo.club",
      token: "t",
      payload: { email: "u@p.club" },
      fetchImpl,
    });
    expect(result.ok).toBe(true);
    expect(result.status).toBe(502);
    expect(result.body).toBeNull();
  });
});


// ─────────────────────────────────────────────────────────────────────
// dispatchProWelcome — orchestrator that tries Python primary, falls
// back to GH Actions when Python is unreachable.
// ─────────────────────────────────────────────────────────────────────

describe("dispatchProWelcome orchestrator", () => {
  const ORIGINAL_INTERNAL_TOKEN = process.env.PULPO_INTERNAL_TOKEN;
  const ORIGINAL_GH_TOKEN = process.env.GITHUB_DISPATCH_TOKEN;

  beforeEach(() => {
    process.env.PULPO_INTERNAL_TOKEN = "internal_test";
    process.env.GITHUB_DISPATCH_TOKEN = "ghp_test_token";
  });
  afterEach(() => {
    if (ORIGINAL_INTERNAL_TOKEN === undefined) delete process.env.PULPO_INTERNAL_TOKEN;
    else process.env.PULPO_INTERNAL_TOKEN = ORIGINAL_INTERNAL_TOKEN;
    if (ORIGINAL_GH_TOKEN === undefined) delete process.env.GITHUB_DISPATCH_TOKEN;
    else process.env.GITHUB_DISPATCH_TOKEN = ORIGINAL_GH_TOKEN;
  });

  it("returns internal:sent when Python responds 200 with status=sent", async () => {
    const clerk = mockClerk({ publicMetadata: {} });
    // fetchImpl is shared between the internal call AND the GH fallback.
    // First call (to internal) returns success; we assert GH is NOT called.
    const fetchImpl = vi.fn(async (url) => {
      if (url.endsWith("/api/internal/welcome-send")) {
        return {
          status: 200,
          json: async () => ({ status: "sent", message_id: "re_xyz", latency_ms: 1800 }),
        };
      }
      throw new Error("unexpected fetch: " + url);
    });
    const result = await dispatchProWelcome({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl, internalBaseUrl: "https://pulpo.club",
    });
    expect(result).toBe("internal:sent");
    // Exactly ONE fetch — to the Python endpoint. GH was not invoked.
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("returns internal:skipped:<reason> when Python responds 200 with status=skipped", async () => {
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = vi.fn(async () => ({
      status: 200,
      json: async () => ({ status: "skipped", reason: "already_sent" }),
    }));
    const result = await dispatchProWelcome({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl, internalBaseUrl: "https://pulpo.club",
    });
    expect(result).toBe("internal:skipped:already_sent");
  });

  it("falls back to GH Actions when Python fetch throws", async () => {
    const clerk = mockClerk({ publicMetadata: {} });
    let calls = 0;
    const fetchImpl = vi.fn(async (url) => {
      calls += 1;
      if (calls === 1) {
        // First call: internal endpoint — simulate network failure.
        throw new Error("ECONNREFUSED");
      }
      // Second call: GH Actions dispatch (the fallback).
      return { status: 204, text: async () => "" };
    });
    const result = await dispatchProWelcome({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl, internalBaseUrl: "https://pulpo.club",
    });
    expect(result).toBe("dispatched");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    // Verify the second call hit GitHub.
    expect(fetchImpl.mock.calls[1][0]).toContain("api.github.com");
  });

  it("does NOT fall back when Python returns 500 (dispatcher attempted)", async () => {
    // If Python's dispatcher returned status=failed, the send was
    // attempted — a GH retry would risk a duplicate Resend call.
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = vi.fn(async () => ({
      status: 500,
      json: async () => ({ status: "failed", reason: "send_failed" }),
    }));
    const result = await dispatchProWelcome({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl, internalBaseUrl: "https://pulpo.club",
    });
    expect(result).toBe("internal:http_500");
    expect(fetchImpl).toHaveBeenCalledOnce();  // No fallback fired.
  });

  it("skips Python entirely + uses GH directly when PULPO_INTERNAL_TOKEN is unset", async () => {
    delete process.env.PULPO_INTERNAL_TOKEN;
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = vi.fn(async () => ({ status: 204, text: async () => "" }));
    const result = await dispatchProWelcome({
      clerk, clerkUserId: "user_123", email: "user@pulpo.club",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl, internalBaseUrl: "https://pulpo.club",
    });
    expect(result).toBe("dispatched");
    // Only GH was called.
    expect(fetchImpl).toHaveBeenCalledOnce();
    expect(fetchImpl.mock.calls[0][0]).toContain("api.github.com");
  });

  it("returns skipped:missing_input without calling either path when email is empty", async () => {
    const clerk = mockClerk({ publicMetadata: {} });
    const fetchImpl = vi.fn();
    const result = await dispatchProWelcome({
      clerk, clerkUserId: "user_123", email: "",
      source: "stripe.checkout.auth_gated", distinctId: "user_123", t0: Date.now(),
      fetchImpl, internalBaseUrl: "https://pulpo.club",
    });
    expect(result).toBe("skipped:missing_input");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
