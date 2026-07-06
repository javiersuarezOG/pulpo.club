// Unit tests for api/_capi.js — the server-side conversion dispatch (P0-2).
// Pure payload builders + the env-gated / best-effort senders. No network:
// senders take an injectable fetchImpl.

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import crypto from "node:crypto";
import {
  hashEmail,
  buildMetaPurchasePayload,
  buildGoogleClickConversion,
  sendMetaConversion,
  sendGoogleConversion,
  sendPurchaseConversions,
  isAnyConfigured,
  resultStatus,
} from "../../api/_capi.js";

const CAPI_ENV = [
  "META_PIXEL_ID", "META_CAPI_ACCESS_TOKEN", "META_CAPI_TEST_CODE",
  "GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_CONVERSION_ACTION_ID", "GOOGLE_ADS_DEVELOPER_TOKEN",
  "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
];
function clearEnv() { for (const k of CAPI_ENV) delete process.env[k]; }
beforeEach(clearEnv);
afterEach(clearEnv);

describe("hashEmail", () => {
  it("normalizes (trim + lowercase) then SHA-256", () => {
    const expected = crypto.createHash("sha256").update("buyer@example.com").digest("hex");
    expect(hashEmail("  Buyer@Example.COM ")).toBe(expected);
  });
  it("returns null for empty / non-string (never sends an empty hash)", () => {
    expect(hashEmail("")).toBeNull();
    expect(hashEmail(null)).toBeNull();
    expect(hashEmail(123)).toBeNull();
  });
});

describe("buildMetaPurchasePayload", () => {
  it("builds a Purchase event: hashed email, major-unit value, dedup id", () => {
    const e = buildMetaPurchasePayload({
      email: "b@x.com", valueCents: 999, currency: "USD",
      eventId: "evt_1", eventSourceUrl: "https://pulpo.club/start", eventTime: 1000,
    }).data[0];
    expect(e.event_name).toBe("Purchase");
    expect(e.action_source).toBe("website");
    expect(e.event_id).toBe("evt_1");
    expect(e.event_time).toBe(1000);
    expect(e.custom_data).toEqual({ currency: "usd", value: 9.99 });
    expect(e.user_data.em).toEqual([hashEmail("b@x.com")]);
    expect(e.user_data).not.toHaveProperty("client_ip_address");
  });
  it("omits em when no email; includes fbc/fbp/ip/ua when present", () => {
    const e = buildMetaPurchasePayload({
      fbc: "fb.1", fbp: "fb.2", clientIp: "1.2.3.4", userAgent: "UA", valueCents: 0,
    }).data[0];
    expect(e.user_data).not.toHaveProperty("em");
    expect(e.user_data.fbc).toBe("fb.1");
    expect(e.user_data.client_ip_address).toBe("1.2.3.4");
    expect(e.custom_data.value).toBe(0);
  });
});

describe("buildGoogleClickConversion", () => {
  it("builds a click conversion with resource name + uppercase currency", () => {
    const b = buildGoogleClickConversion({
      gclid: "g1", conversionActionResource: "customers/123/conversionActions/456",
      valueCents: 1200, currency: "usd", conversionDateTime: "2026-07-06 11:00:00+00:00", orderId: "evt_1",
    });
    expect(b.partialFailure).toBe(true);
    expect(b.conversions[0]).toMatchObject({
      gclid: "g1", conversionAction: "customers/123/conversionActions/456",
      conversionValue: 12, currencyCode: "USD", orderId: "evt_1",
    });
  });
});

describe("sendMetaConversion — env-gated, best-effort", () => {
  it("no-ops when unconfigured (ships dark)", async () => {
    expect(await sendMetaConversion({ email: "b@x.com" })).toEqual({ skipped: "unconfigured" });
  });
  it("no-ops when configured but no identifier", async () => {
    process.env.META_PIXEL_ID = "PIX"; process.env.META_CAPI_ACCESS_TOKEN = "TOK";
    expect(await sendMetaConversion({ valueCents: 100 })).toEqual({ skipped: "no_identifier" });
  });
  it("POSTs to the Graph API when configured", async () => {
    process.env.META_PIXEL_ID = "PIX"; process.env.META_CAPI_ACCESS_TOKEN = "TOK";
    let captured = null;
    const fetchImpl = async (url, opts) => {
      captured = { url, opts };
      return { ok: true, status: 200, json: async () => ({ fbtrace_id: "t1" }) };
    };
    const r = await sendMetaConversion(
      { email: "b@x.com", valueCents: 999, currency: "usd", eventId: "evt_1" },
      { fetchImpl },
    );
    expect(r.sent).toBe(true);
    expect(captured.url).toContain("graph.facebook.com");
    expect(captured.url).toContain("/PIX/events");
    const body = JSON.parse(captured.opts.body);
    expect(body.data[0].event_name).toBe("Purchase");
    expect(body.data[0].user_data.em[0]).toBe(hashEmail("b@x.com"));
  });
  it("never throws on a fetch failure", async () => {
    process.env.META_PIXEL_ID = "PIX"; process.env.META_CAPI_ACCESS_TOKEN = "TOK";
    const fetchImpl = async () => { throw new Error("network down"); };
    const r = await sendMetaConversion({ email: "b@x.com" }, { fetchImpl });
    expect(r.sent).toBe(false);
    expect(r.error).toContain("network down");
  });
});

describe("sendGoogleConversion — env-gated, needs gclid", () => {
  it("no-ops when unconfigured", async () => {
    expect(await sendGoogleConversion({ gclid: "g1" })).toEqual({ skipped: "unconfigured" });
  });
  it("no-ops when configured but no gclid", async () => {
    process.env.GOOGLE_ADS_CUSTOMER_ID = "123-456-7890";
    process.env.GOOGLE_ADS_CONVERSION_ACTION_ID = "456";
    process.env.GOOGLE_ADS_DEVELOPER_TOKEN = "dev";
    expect(await sendGoogleConversion({ valueCents: 100 })).toEqual({ skipped: "no_gclid" });
  });
});

describe("orchestrator + helpers", () => {
  it("sendPurchaseConversions returns per-network results and never rejects when dark", async () => {
    const r = await sendPurchaseConversions({ email: "b@x.com", valueCents: 999 });
    expect(r.meta.skipped).toBe("unconfigured");
    expect(r.google.skipped).toBe("unconfigured");
  });
  it("isAnyConfigured reflects env (Meta OR Google credentialed)", () => {
    expect(isAnyConfigured()).toBe(false);
    process.env.META_PIXEL_ID = "PIX"; process.env.META_CAPI_ACCESS_TOKEN = "TOK";
    expect(isAnyConfigured()).toBe(true);
  });
  it("resultStatus maps sent / skip-reason / error", () => {
    expect(resultStatus({ sent: true })).toBe("sent");
    expect(resultStatus({ skipped: "no_gclid" })).toBe("no_gclid");
    expect(resultStatus({ sent: false, error: "x" })).toBe("error");
    expect(resultStatus(null)).toBe("none");
  });
});
