// Unit tests for api/clerk/webhook.js — runs under vitest (`npm test`).
// Verifies the Svix signature check, the event-mapping table, the
// PostHog prop extraction, and the handler's error/success paths.
// Real Clerk and PostHog never get called; we test the pure handler.

import { describe, it, expect, beforeEach } from "vitest";
import crypto from "node:crypto";

import handler, {
  EVENT_MAP,
  pickPostHogProps,
  distinctIdFor,
  hashEmail,
} from "../../api/clerk/webhook.js";

// Mirror Svix's signing: HMAC-SHA256 over `${id}.${ts}.${body}` using the
// base64-decoded secret. Same algorithm exercised by the Resend webhook
// tests; copied verbatim so the two test suites stay independent.
function makeSignature(secret, id, ts, body) {
  const stripped = secret.startsWith("whsec_") ? secret.slice(6) : secret;
  let key;
  try { key = Buffer.from(stripped, "base64"); } catch { key = Buffer.from(secret, "utf8"); }
  if (key.length === 0) key = Buffer.from(secret, "utf8");
  const sig = crypto.createHmac("sha256", key).update(`${id}.${ts}.${body}`).digest("base64");
  return `v1,${sig}`;
}

function mockRes() {
  return {
    statusCode: 200,
    headers: {},
    body: null,
    status(code) { this.statusCode = code; return this; },
    setHeader(k, v) { this.headers[k] = v; return this; },
    json(payload) { this.body = payload; return this; },
  };
}

const TEST_SECRET = "whsec_dGVzdC1zZWNyZXQtZm9yLXVuaXQtdGVzdHM=";

beforeEach(() => {
  process.env.CLERK_WEBHOOK_SECRET = TEST_SECRET;
  // PostHog token absent → silent no-op (capture is a no-op then). Handler
  // still 200s; that's a separate code path tested in the success cases.
  delete process.env.POSTHOG_PROJECT_TOKEN;
});

describe("EVENT_MAP", () => {
  it("maps each of the 5 Clerk events we care about", () => {
    expect(EVENT_MAP["email.created"]).toBe("clerk.email_attempted");
    expect(EVENT_MAP["invitation.created"]).toBe("clerk.invitation_created");
    expect(EVENT_MAP["invitation.accepted"]).toBe("clerk.invitation_accepted");
    expect(EVENT_MAP["invitation.revoked"]).toBe("clerk.invitation_revoked");
    expect(EVENT_MAP["user.created"]).toBe("clerk.user_created");
  });
});

describe("hashEmail", () => {
  it("returns null when no email", () => {
    expect(hashEmail(null)).toBeNull();
    expect(hashEmail("")).toBeNull();
    expect(hashEmail(undefined)).toBeNull();
  });

  it("is case- and whitespace-insensitive", () => {
    const a = hashEmail("Sebastian@Example.com");
    const b = hashEmail("  sebastian@example.com ");
    expect(a).toBe(b);
  });

  it("matches _posthog.emailDistinctId's hash slice (16 hex chars)", () => {
    // Same algorithm: sha256 → hex → first 16 chars. Lock the contract
    // so funnel-join with webhook.checkout_completed never breaks.
    const h = hashEmail("user@example.com");
    expect(h).toMatch(/^[0-9a-f]{16}$/);
  });
});

describe("pickPostHogProps", () => {
  it("email.created — extracts slug, delivered_by_clerk, status, email_hash", () => {
    const out = pickPostHogProps("email.created", {
      data: {
        id: "ema_123",
        to_email_address: "sebastian@example.com",
        slug: "invitation",
        delivered_by_clerk: true,
        status: "delivered",
        subject: "Welcome to Pulpo Pro",
      },
    });
    expect(out.clerk_event).toBe("email.created");
    expect(out.slug).toBe("invitation");
    expect(out.delivered_by_clerk).toBe(true);
    expect(out.status).toBe("delivered");
    expect(out.email_hash).toBe(hashEmail("sebastian@example.com"));
    expect(out.message_subject).toBe("Welcome to Pulpo Pro");
    expect(out.message_id).toBe("ema_123");
  });

  it("email.created — delivered_by_clerk=false surfaces as the literal false", () => {
    // This is the diagnostic case we care about most — Clerk thinks it
    // tried and failed. Don't coerce to null.
    const out = pickPostHogProps("email.created", {
      data: {
        id: "ema_456",
        to_email_address: "sebastian@example.com",
        slug: "invitation",
        delivered_by_clerk: false,
        status: "failed",
      },
    });
    expect(out.delivered_by_clerk).toBe(false);
    expect(out.status).toBe("failed");
  });

  it("invitation.created — extracts invitation_id, email_hash, expires_at", () => {
    const out = pickPostHogProps("invitation.created", {
      data: {
        id: "inv_abc",
        email_address: "newuser@example.com",
        expires_at: 1735689600,
        redirect_url: "https://pulpo.club/account?welcome=1",
      },
    });
    expect(out.invitation_id).toBe("inv_abc");
    expect(out.email_hash).toBe(hashEmail("newuser@example.com"));
    expect(out.expires_at).toBe(1735689600);
    expect(out.redirect_url).toBe("https://pulpo.club/account?welcome=1");
  });

  it("invitation.accepted — carries user_id alongside invitation_id", () => {
    const out = pickPostHogProps("invitation.accepted", {
      data: {
        id: "inv_xyz",
        email_address: "newuser@example.com",
        accepted_by_user_id: "user_789",
      },
    });
    expect(out.invitation_id).toBe("inv_xyz");
    expect(out.user_id).toBe("user_789");
    expect(out.email_hash).toBe(hashEmail("newuser@example.com"));
  });

  it("invitation.revoked — minimal, just id + hash", () => {
    const out = pickPostHogProps("invitation.revoked", {
      data: { id: "inv_rev", email_address: "x@example.com" },
    });
    expect(out.invitation_id).toBe("inv_rev");
    expect(out.email_hash).toBe(hashEmail("x@example.com"));
  });

  it("user.created — picks primary email + source=invitation when invited", () => {
    const out = pickPostHogProps("user.created", {
      data: {
        id: "user_111",
        primary_email_address_id: "idn_2",
        email_addresses: [
          { id: "idn_1", email_address: "secondary@example.com" },
          { id: "idn_2", email_address: "primary@example.com" },
        ],
        private_metadata: { invitation_id: "inv_xyz" },
      },
    });
    expect(out.user_id).toBe("user_111");
    expect(out.email_hash).toBe(hashEmail("primary@example.com"));
    expect(out.source).toBe("invitation");
  });

  it("user.created — source=oauth when external accounts present", () => {
    const out = pickPostHogProps("user.created", {
      data: {
        id: "user_222",
        primary_email_address_id: "idn_1",
        email_addresses: [{ id: "idn_1", email_address: "oauth@example.com" }],
        external_accounts: [{ provider: "google" }],
      },
    });
    expect(out.source).toBe("oauth");
  });

  it("user.created — source=direct otherwise", () => {
    const out = pickPostHogProps("user.created", {
      data: {
        id: "user_333",
        primary_email_address_id: "idn_1",
        email_addresses: [{ id: "idn_1", email_address: "direct@example.com" }],
      },
    });
    expect(out.source).toBe("direct");
  });
});

describe("distinctIdFor", () => {
  it("prefers email_hash for joinability with webhook.checkout_completed", () => {
    expect(distinctIdFor({ email_hash: "abc123" })).toBe("email:abc123");
  });

  it("falls back to user_id when no email", () => {
    expect(distinctIdFor({ user_id: "user_777" })).toBe("user:user_777");
  });

  it("falls back to server bucket as last resort", () => {
    expect(distinctIdFor({})).toBe("server:clerk_webhook");
  });
});

describe("handler", () => {
  it("405s on GET", async () => {
    const res = mockRes();
    await handler({ method: "GET", headers: {}, body: "" }, res);
    expect(res.statusCode).toBe(405);
  });

  it("503s when CLERK_WEBHOOK_SECRET is absent (gracefully disabled)", async () => {
    delete process.env.CLERK_WEBHOOK_SECRET;
    const res = mockRes();
    await handler({ method: "POST", headers: {}, body: "{}" }, res);
    expect(res.statusCode).toBe(503);
    expect(res.body.error).toBe("not_configured");
  });

  it("401s on bad signature", async () => {
    const body = '{"type":"invitation.created","data":{"id":"inv_x"}}';
    const ts = Math.floor(Date.now() / 1000).toString();
    const req = {
      method: "POST",
      headers: {
        "svix-id": "msg_x",
        "svix-timestamp": ts,
        "svix-signature": "v1,not-the-right-sig",
      },
      body,
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(401);
    expect(res.body.error).toBe("bad_signature");
  });

  it("401s when Svix headers are missing entirely", async () => {
    const res = mockRes();
    await handler({ method: "POST", headers: {}, body: "{}" }, res);
    expect(res.statusCode).toBe(401);
  });

  it("400s on a bad JSON body that nonetheless has a valid signature", async () => {
    const body = "not json";
    const ts = Math.floor(Date.now() / 1000).toString();
    const req = {
      method: "POST",
      headers: {
        "svix-id": "msg_y",
        "svix-timestamp": ts,
        "svix-signature": makeSignature(TEST_SECRET, "msg_y", ts, body),
      },
      body,
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toBe("bad_json");
  });

  it("200s + ignored:true for unmapped events", async () => {
    const body = '{"type":"org.created","data":{}}';
    const ts = Math.floor(Date.now() / 1000).toString();
    const req = {
      method: "POST",
      headers: {
        "svix-id": "msg_o",
        "svix-timestamp": ts,
        "svix-signature": makeSignature(TEST_SECRET, "msg_o", ts, body),
      },
      body,
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(200);
    expect(res.body.ignored).toBe(true);
  });

  it("200s on a valid email.created event (the diagnostic-critical case)", async () => {
    // This is THE event we lacked visibility on. The handler must
    // happy-path it without error.
    const body = JSON.stringify({
      type: "email.created",
      data: {
        id: "ema_smoke",
        to_email_address: "smoketest@example.com",
        slug: "invitation",
        delivered_by_clerk: true,
        status: "delivered",
      },
    });
    const ts = Math.floor(Date.now() / 1000).toString();
    const req = {
      method: "POST",
      headers: {
        "svix-id": "msg_email",
        "svix-timestamp": ts,
        "svix-signature": makeSignature(TEST_SECRET, "msg_email", ts, body),
      },
      body,
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(200);
    expect(res.body.ok).toBe(true);
  });

  it("200s on a valid invitation.created event", async () => {
    const body = JSON.stringify({
      type: "invitation.created",
      data: {
        id: "inv_smoke",
        email_address: "newuser@example.com",
        expires_at: 1735689600,
      },
    });
    const ts = Math.floor(Date.now() / 1000).toString();
    const req = {
      method: "POST",
      headers: {
        "svix-id": "msg_inv",
        "svix-timestamp": ts,
        "svix-signature": makeSignature(TEST_SECRET, "msg_inv", ts, body),
      },
      body,
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(200);
    expect(res.body.ok).toBe(true);
  });

  it("config.api.bodyParser is false (Svix needs raw bytes)", () => {
    expect(handler.config).toBeDefined();
    expect(handler.config.api.bodyParser).toBe(false);
  });
});
