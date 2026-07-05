// Unit tests for api/resend-webhook.js — runs under vitest (`npm test`).
// Verifies the Svix signature check + the body → PostHog mapping.
// Real Resend never gets called; we test pure helpers.

import { describe, it, expect, beforeEach } from "vitest";
import crypto from "node:crypto";

import handler, {
  verifySvixSignature,
  pickPostHogProps,
  EVENT_MAP,
  distinctIdFor,
} from "../../api/resend-webhook.js";
import { recipientHash } from "../../api/_activation_email.js";
import { emailDistinctId } from "../../api/_posthog.js";

function makeSignature(secret, id, ts, body) {
  // Mirror Svix's signing: HMAC-SHA256 over `${id}.${ts}.${body}` using the
  // base64-decoded secret (or raw if not base64).
  const stripped = secret.startsWith("whsec_") ? secret.slice(6) : secret;
  let key;
  try { key = Buffer.from(stripped, "base64"); } catch { key = Buffer.from(secret, "utf8"); }
  if (key.length === 0) key = Buffer.from(secret, "utf8");
  const sig = crypto
    .createHmac("sha256", key)
    .update(`${id}.${ts}.${body}`)
    .digest("base64");
  return `v1,${sig}`;
}

function mockRes() {
  const res = {
    statusCode: 200,
    headers: {},
    body: null,
    status(code) { this.statusCode = code; return this; },
    setHeader(k, v) { this.headers[k] = v; return this; },
    json(payload) { this.body = payload; return this; },
  };
  return res;
}

beforeEach(() => {
  process.env.RESEND_WEBHOOK_SECRET = "whsec_dGVzdC1zZWNyZXQtZm9yLXVuaXQtdGVzdHM=";
  // PostHog token absent → silent no-op (the handler still 200s).
  delete process.env.POSTHOG_PROJECT_TOKEN;
});

describe("verifySvixSignature", () => {
  const secret = "whsec_dGVzdC1zZWNyZXQtZm9yLXVuaXQtdGVzdHM=";
  const ts = Math.floor(Date.now() / 1000).toString();
  const id = "msg_abc";
  const body = '{"type":"email.delivered"}';

  it("accepts a freshly-signed payload", () => {
    const sig = makeSignature(secret, id, ts, body);
    expect(verifySvixSignature({
      secret, svixId: id, svixTimestamp: ts, svixSignature: sig, body,
    })).toBe(true);
  });

  it("rejects when timestamp is too old", () => {
    const oldTs = (Math.floor(Date.now() / 1000) - 3600).toString();
    const sig = makeSignature(secret, id, oldTs, body);
    expect(verifySvixSignature({
      secret, svixId: id, svixTimestamp: oldTs, svixSignature: sig, body,
    })).toBe(false);
  });

  it("rejects when signature doesn't match", () => {
    const sig = makeSignature(secret, id, ts, body);
    const tampered = sig.replace(/.$/, "X");
    expect(verifySvixSignature({
      secret, svixId: id, svixTimestamp: ts, svixSignature: tampered, body,
    })).toBe(false);
  });

  it("accepts a space-separated multi-signature header", () => {
    const sig = makeSignature(secret, id, ts, body);
    const combined = `v1,wrongsignature ${sig}`;
    expect(verifySvixSignature({
      secret, svixId: id, svixTimestamp: ts, svixSignature: combined, body,
    })).toBe(true);
  });

  it("returns false when secret is empty", () => {
    expect(verifySvixSignature({
      secret: "", svixId: id, svixTimestamp: ts, svixSignature: "v1,sig", body,
    })).toBe(false);
  });
});

describe("pickPostHogProps", () => {
  it("extracts recipient_hash + issue_number from tags", () => {
    const out = pickPostHogProps("email.opened", {
      data: {
        email_id: "msg_1",
        tags: [
          { name: "recipient_hash", value: "abc123" },
          { name: "issue_number", value: "5" },
        ],
      },
    });
    expect(out.recipient_hash).toBe("abc123");
    expect(out.issue_number).toBe(5);
    expect(out.message_id).toBe("msg_1");
  });

  it("falls back to headers when tags are absent", () => {
    const out = pickPostHogProps("email.delivered", {
      data: {
        email_id: "msg_2",
        headers: {
          "x-pulpo-recipient": "xyz999",
          "x-pulpo-issue": "3",
        },
      },
    });
    expect(out.recipient_hash).toBe("xyz999");
    expect(out.issue_number).toBe(3);
  });

  it("carries target_url for click events", () => {
    const out = pickPostHogProps("email.clicked", {
      data: {
        email_id: "msg_3",
        click: { link: "https://pulpo.club/listing/123" },
      },
    });
    expect(out.target_url).toBe("https://pulpo.club/listing/123");
  });

  it("carries bounce_type for bounce events", () => {
    const out = pickPostHogProps("email.bounced", {
      data: { email_id: "msg_4", bounce: { type: "hard" } },
    });
    expect(out.bounce_type).toBe("hard");
  });

  it("extracts email_type from the `email_type` tag", () => {
    const out = pickPostHogProps("email.delivered", {
      data: {
        email_id: "msg_5",
        tags: [
          { name: "recipient_hash", value: "abc" },
          { name: "email_type", value: "activation" },
        ],
      },
    });
    expect(out.email_type).toBe("activation");
  });

  it("falls back to `x-pulpo-email-type` header for email_type", () => {
    const out = pickPostHogProps("email.sent", {
      data: {
        email_id: "msg_6",
        headers: { "x-pulpo-email-type": "newsletter" },
      },
    });
    expect(out.email_type).toBe("newsletter");
  });

  it("defaults email_type to 'unknown' when neither tag nor header set", () => {
    const out = pickPostHogProps("email.opened", {
      data: { email_id: "msg_7" },
    });
    expect(out.email_type).toBe("unknown");
  });

  it("rejects unknown email_type values (defends dashboard axis)", () => {
    const out = pickPostHogProps("email.sent", {
      data: {
        email_id: "msg_8",
        tags: [{ name: "email_type", value: "marketing_blast_xyz" }],
      },
    });
    expect(out.email_type).toBe("unknown");
  });

  // ── PRD P0-3 — header casing fix + classification_source ──────────
  //
  // Resend preserves header key casing from the sender. The newsletter
  // dispatcher stamps `X-Pulpo-Recipient` capitalized; previously the
  // parser only matched the lowercase variant so the header fallback
  // never resolved. Audit caught this — fixture covers the capitalized
  // header path now.

  it("resolves recipient_hash from capitalized X-Pulpo-Recipient header", () => {
    const out = pickPostHogProps("email.delivered", {
      data: {
        email_id: "msg_cap",
        headers: {
          "X-Pulpo-Recipient": "deadbeef0123abcd",
          "X-Pulpo-Email-Type": "newsletter",
        },
      },
    });
    expect(out.recipient_hash).toBe("deadbeef0123abcd");
    expect(out.email_type).toBe("newsletter");
    expect(out.classification_source).toBe("headers");
  });

  it("classification_source='tags' when tags carry the values", () => {
    const out = pickPostHogProps("email.delivered", {
      data: {
        email_id: "msg_tags",
        tags: [
          { name: "recipient_hash", value: "abc" },
          { name: "email_type", value: "activation" },
        ],
      },
    });
    expect(out.classification_source).toBe("tags");
  });

  it("classification_source='unknown' when nothing is stamped", () => {
    const out = pickPostHogProps("email.delivered", {
      data: { email_id: "msg_naked" },
    });
    expect(out.classification_source).toBe("unknown");
    expect(out.recipient_hash).toBeNull();
    expect(out.email_type).toBe("unknown");
  });

  it("accepts 'contact' as a valid email_type for contact-form sends", () => {
    // PRD P0-3 — api/contact.js now stamps email_type=contact + topic
    // so lifecycle events from the contact form land with a real axis
    // instead of polluting the unknown bucket.
    const out = pickPostHogProps("email.sent", {
      data: {
        email_id: "msg_contact",
        tags: [
          { name: "email_type", value: "contact" },
          { name: "topic", value: "billing" },
        ],
      },
    });
    expect(out.email_type).toBe("contact");
    expect(out.classification_source).toBe("tags");
  });
});

describe("EVENT_MAP", () => {
  it("maps the 7 Resend event types we care about", () => {
    expect(EVENT_MAP["email.sent"]).toBe("newsletter.sent");
    expect(EVENT_MAP["email.delivered"]).toBe("newsletter.delivered");
    expect(EVENT_MAP["email.opened"]).toBe("newsletter.opened");
    expect(EVENT_MAP["email.clicked"]).toBe("newsletter.clicked");
    expect(EVENT_MAP["email.bounced"]).toBe("newsletter.bounced");
    expect(EVENT_MAP["email.complained"]).toBe("newsletter.complained");
    expect(EVENT_MAP["email.delivery_delayed"]).toBe("newsletter.delivery_delayed");
  });
});

describe("distinctIdFor — person stitching (2026-06-30 audit P1-4)", () => {
  it("activation lifecycle stitches to the post-Stripe funnel person (email: prefix)", () => {
    // Activation stamps recipient_hash = sha256(email)[:16], identical to the
    // funnel person id, so its events must land on `email:<hash>` — NOT the
    // orphaned `user:<hash>` the handler used to emit.
    expect(distinctIdFor({ recipient_hash: "abc123def456", email_type: "activation" }))
      .toBe("email:abc123def456");
  });

  it("newsletter stays on user: (salted 24-char hash — a different id space)", () => {
    expect(distinctIdFor({ recipient_hash: "deadbeef001122334455", email_type: "newsletter" }))
      .toBe("user:deadbeef001122334455");
  });

  it("unknown/absent email_type defaults to user: (no accidental stitch)", () => {
    expect(distinctIdFor({ recipient_hash: "x", email_type: "unknown" })).toBe("user:x");
    expect(distinctIdFor({ recipient_hash: "y" })).toBe("user:y");
  });

  it("missing recipient_hash falls back to the server bucket", () => {
    expect(distinctIdFor({ recipient_hash: null, email_type: "activation" }))
      .toBe("server:resend_webhook");
    expect(distinctIdFor({})).toBe("server:resend_webhook");
  });

  it("CONTRACT: activation events land on the SAME person id as the conversion funnel", () => {
    // The stitch only works because recipientHash (producer, api/_activation_email.js)
    // and emailDistinctId (consumer, api/_posthog.js) hash the email identically.
    // Lock that identity: if either drifts, activation lifecycle silently
    // re-orphans onto a separate PostHog person.
    const email = "Buyer@Example.com";
    expect(`email:${recipientHash(email)}`).toBe(emailDistinctId(email));
    expect(distinctIdFor({ recipient_hash: recipientHash(email), email_type: "activation" }))
      .toBe(emailDistinctId(email));
  });
});

describe("handler", () => {
  const secret = "whsec_dGVzdC1zZWNyZXQtZm9yLXVuaXQtdGVzdHM=";

  it("405s on GET", async () => {
    const req = { method: "GET", headers: {}, body: "" };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(405);
  });

  it("503s when secret env is absent", async () => {
    delete process.env.RESEND_WEBHOOK_SECRET;
    const req = { method: "POST", headers: {}, body: "{}" };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(503);
    expect(res.body.error).toBe("not_configured");
  });

  it("401s on bad signature", async () => {
    const body = '{"type":"email.delivered","data":{"email_id":"x"}}';
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

  it("200s and ignores unmapped event types", async () => {
    const body = '{"type":"email.something_new","data":{}}';
    const ts = Math.floor(Date.now() / 1000).toString();
    const req = {
      method: "POST",
      headers: {
        "svix-id": "msg_a",
        "svix-timestamp": ts,
        "svix-signature": makeSignature(secret, "msg_a", ts, body),
      },
      body,
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(200);
    expect(res.body.ignored).toBe(true);
  });

  it("200s on a valid delivered event", async () => {
    const body = JSON.stringify({
      type: "email.delivered",
      data: {
        email_id: "msg_yz",
        tags: [
          { name: "recipient_hash", value: "abc" },
          { name: "issue_number", value: "1" },
        ],
      },
    });
    const ts = Math.floor(Date.now() / 1000).toString();
    const req = {
      method: "POST",
      headers: {
        "svix-id": "msg_yz",
        "svix-timestamp": ts,
        "svix-signature": makeSignature(secret, "msg_yz", ts, body),
      },
      body,
    };
    const res = mockRes();
    await handler(req, res);
    expect(res.statusCode).toBe(200);
    expect(res.body.ok).toBe(true);
  });
});
