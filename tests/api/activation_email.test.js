// Unit tests for api/_activation_email.js — verifies the Resend send
// surface contract: payload shape, locale routing, tag/header join
// keys (used by api/resend-webhook.js to chain lifecycle events back
// into PostHog), and never-throws error semantics.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  sendActivationEmail,
  recipientHash,
  pickLocale,
  TEMPLATES,
  DEFAULT_FROM,
} from "../../api/_activation_email.js";

const ORIG_FETCH = global.fetch;

function mockFetch(impl) {
  global.fetch = vi.fn(impl);
}

beforeEach(() => {
  process.env.RESEND_API_KEY = "test_resend_key_re_abc123";
  delete process.env.PULPO_ACTIVATION_FROM_EMAIL;
});

afterEach(() => {
  global.fetch = ORIG_FETCH;
  vi.restoreAllMocks();
});

describe("recipientHash", () => {
  it("returns empty string when email is null/undefined", () => {
    expect(recipientHash(null)).toBe("");
    expect(recipientHash(undefined)).toBe("");
    expect(recipientHash("")).toBe("");
  });

  it("is case- and whitespace-insensitive (same join key for variant casing)", () => {
    expect(recipientHash("User@Example.COM"))
      .toBe(recipientHash("  user@example.com  "));
  });

  it("matches the api/_posthog.js emailDistinctId 16-hex-char algorithm", () => {
    const h = recipientHash("user@example.com");
    expect(h).toMatch(/^[0-9a-f]{16}$/);
  });
});

describe("pickLocale", () => {
  it("returns 'en' for null/empty/unknown locales", () => {
    expect(pickLocale(null)).toBe("en");
    expect(pickLocale("")).toBe("en");
    expect(pickLocale("fr")).toBe("en");
    expect(pickLocale("de-DE")).toBe("en");
  });

  it("returns 'es' for any Spanish variant", () => {
    expect(pickLocale("es")).toBe("es");
    expect(pickLocale("es-419")).toBe("es");
    expect(pickLocale("ES")).toBe("es");
    expect(pickLocale("  es-MX ")).toBe("es");
  });

  it("returns 'en' for English variants", () => {
    expect(pickLocale("en")).toBe("en");
    expect(pickLocale("en-US")).toBe("en");
  });
});

describe("TEMPLATES", () => {
  it("has both en and es locales with subject, html, text", () => {
    for (const lc of ["en", "es"]) {
      const t = TEMPLATES[lc];
      expect(t.subject).toBeTruthy();
      expect(typeof t.html).toBe("function");
      expect(typeof t.text).toBe("function");
      const action = "https://pulpo.club/__test_action_url__";
      expect(t.html(action)).toContain(action);
      expect(t.text(action)).toContain(action);
    }
  });

  it("EN subject mentions Pulpo Pro and activation", () => {
    expect(TEMPLATES.en.subject.toLowerCase()).toContain("pulpo pro");
  });

  it("ES subject is in Spanish (uses 'suscripción')", () => {
    expect(TEMPLATES.es.subject.toLowerCase()).toContain("suscripción");
  });
});

describe("sendActivationEmail — auth + validation", () => {
  it("returns ok:false when RESEND_API_KEY is missing", async () => {
    delete process.env.RESEND_API_KEY;
    const out = await sendActivationEmail({
      email: "a@example.com", locale: "en", actionUrl: "https://x",
    });
    expect(out.ok).toBe(false);
    expect(out.error).toContain("RESEND_API_KEY");
  });

  it("returns ok:false when email is missing", async () => {
    const out = await sendActivationEmail({
      email: "", locale: "en", actionUrl: "https://x",
    });
    expect(out.ok).toBe(false);
  });

  it("returns ok:false when actionUrl is missing", async () => {
    const out = await sendActivationEmail({
      email: "a@example.com", locale: "en", actionUrl: "",
    });
    expect(out.ok).toBe(false);
  });
});

describe("sendActivationEmail — happy path", () => {
  it("returns ok:true + message_id when Resend accepts (200)", async () => {
    mockFetch(async () => ({
      ok: true, status: 200,
      json: async () => ({ id: "ema_test_123" }),
    }));
    const out = await sendActivationEmail({
      email: "user@example.com",
      locale: "en",
      actionUrl: "https://pulpo.club/__action__",
      sessionId: "cs_test_smoke",
    });
    expect(out.ok).toBe(true);
    expect(out.message_id).toBe("ema_test_123");
    expect(out.status_code).toBe(200);
  });

  it("uses DEFAULT_FROM when PULPO_ACTIVATION_FROM_EMAIL is unset", async () => {
    let captured;
    mockFetch(async (_url, init) => {
      captured = JSON.parse(init.body);
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    await sendActivationEmail({
      email: "u@example.com", locale: "en",
      actionUrl: "https://x", sessionId: "cs_1",
    });
    expect(captured.from).toBe(DEFAULT_FROM);
  });

  it("honors PULPO_ACTIVATION_FROM_EMAIL override", async () => {
    process.env.PULPO_ACTIVATION_FROM_EMAIL = "Custom <hi@pulpo.club>";
    let captured;
    mockFetch(async (_url, init) => {
      captured = JSON.parse(init.body);
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    await sendActivationEmail({
      email: "u@example.com", locale: "en",
      actionUrl: "https://x", sessionId: "cs_1",
    });
    expect(captured.from).toBe("Custom <hi@pulpo.club>");
  });

  it("ES locale picks Spanish subject + body", async () => {
    let captured;
    mockFetch(async (_url, init) => {
      captured = JSON.parse(init.body);
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    await sendActivationEmail({
      email: "u@example.com", locale: "es-419",
      actionUrl: "https://pulpo.club/__action__", sessionId: "cs_1",
    });
    expect(captured.subject).toContain("suscripción");
    expect(captured.html).toContain("https://pulpo.club/__action__");
    expect(captured.text).toContain("https://pulpo.club/__action__");
  });

  it("EN locale picks English subject + body", async () => {
    let captured;
    mockFetch(async (_url, init) => {
      captured = JSON.parse(init.body);
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    await sendActivationEmail({
      email: "u@example.com", locale: "en",
      actionUrl: "https://x", sessionId: "cs_1",
    });
    expect(captured.subject.toLowerCase()).toContain("pulpo pro");
    expect(captured.html).toContain("Set up my Pulpo Pro account");
  });

  it("unknown locale falls back to English", async () => {
    let captured;
    mockFetch(async (_url, init) => {
      captured = JSON.parse(init.body);
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    await sendActivationEmail({
      email: "u@example.com", locale: "fr",
      actionUrl: "https://x", sessionId: "cs_1",
    });
    expect(captured.subject.toLowerCase()).toContain("pulpo pro");
    expect(captured.html).toContain("Set up my Pulpo Pro account");
  });
});

describe("sendActivationEmail — tags + headers (funnel join keys)", () => {
  it("stamps recipient_hash, email_type=activation, session_id, locale as Resend tags", async () => {
    let captured;
    mockFetch(async (_url, init) => {
      captured = JSON.parse(init.body);
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    const email = "tagged@example.com";
    await sendActivationEmail({
      email, locale: "en",
      actionUrl: "https://x", sessionId: "cs_tag_test",
    });
    const tagFor = (name) =>
      (captured.tags.find((t) => t.name === name) || {}).value;
    expect(tagFor("recipient_hash")).toBe(recipientHash(email));
    expect(tagFor("email_type")).toBe("activation");
    expect(tagFor("session_id")).toBe("cs_tag_test");
    expect(tagFor("locale")).toBe("en");
  });

  it("stamps x-pulpo-* headers for clients that lose tags", async () => {
    let captured;
    mockFetch(async (_url, init) => {
      captured = JSON.parse(init.body);
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    const email = "headers@example.com";
    await sendActivationEmail({
      email, locale: "en",
      actionUrl: "https://x", sessionId: "cs_headers_test",
    });
    expect(captured.headers["x-pulpo-recipient"]).toBe(recipientHash(email));
    expect(captured.headers["x-pulpo-email-type"]).toBe("activation");
    expect(captured.headers["x-pulpo-session"]).toBe("cs_headers_test");
  });

  it("omits session_id tag + header when sessionId is missing", async () => {
    let captured;
    mockFetch(async (_url, init) => {
      captured = JSON.parse(init.body);
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    await sendActivationEmail({
      email: "u@example.com", locale: "en",
      actionUrl: "https://x", sessionId: null,
    });
    expect(captured.tags.find((t) => t.name === "session_id")).toBeUndefined();
    expect(captured.headers["x-pulpo-session"]).toBeUndefined();
  });
});

describe("sendActivationEmail — error semantics (never throws)", () => {
  it("returns ok:false on Resend 4xx, never throws", async () => {
    mockFetch(async () => ({
      ok: false, status: 422,
      json: async () => ({ message: "Invalid email" }),
    }));
    const out = await sendActivationEmail({
      email: "u@example.com", locale: "en",
      actionUrl: "https://x", sessionId: "cs_4xx",
    });
    expect(out.ok).toBe(false);
    expect(out.status_code).toBe(422);
    expect(out.error).toBe("Invalid email");
  });

  it("returns ok:false on Resend 5xx, never throws", async () => {
    mockFetch(async () => ({
      ok: false, status: 503,
      json: async () => ({}),
    }));
    const out = await sendActivationEmail({
      email: "u@example.com", locale: "en",
      actionUrl: "https://x", sessionId: "cs_5xx",
    });
    expect(out.ok).toBe(false);
    expect(out.status_code).toBe(503);
    expect(out.error).toBe("http_503");
  });

  it("returns ok:false on fetch failure (network error), never throws", async () => {
    mockFetch(async () => { throw new Error("ECONNRESET"); });
    const out = await sendActivationEmail({
      email: "u@example.com", locale: "en",
      actionUrl: "https://x", sessionId: "cs_net",
    });
    expect(out.ok).toBe(false);
    expect(out.error).toContain("ECONNRESET");
  });

  it("uses Authorization header with the API key", async () => {
    let captured;
    mockFetch(async (_url, init) => {
      captured = init;
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    await sendActivationEmail({
      email: "u@example.com", locale: "en",
      actionUrl: "https://x", sessionId: "cs_auth",
    });
    expect(captured.headers["Authorization"]).toBe("Bearer test_resend_key_re_abc123");
  });

  it("POSTs to api.resend.com/emails", async () => {
    let capturedUrl;
    mockFetch(async (url) => {
      capturedUrl = url;
      return { ok: true, status: 200, json: async () => ({ id: "x" }) };
    });
    await sendActivationEmail({
      email: "u@example.com", locale: "en",
      actionUrl: "https://x", sessionId: "cs_url",
    });
    expect(capturedUrl).toBe("https://api.resend.com/emails");
  });
});
