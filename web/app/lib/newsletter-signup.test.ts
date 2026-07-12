// subscribeEmail — the shared transport for the home hero (AccessBlock) +
// EmailCaptureModal. The classification here decides whether becomeFreeMember
// gets `returning:true` (suppress the octopus celebration) — so mapping the
// server's dup signals correctly is what keeps QA bug-3 fixed on the LIVE
// surface (the earlier fix only touched the legacy inline EmailCapture).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { subscribeEmail } from "./newsletter-signup";

vi.mock("./campaign", () => ({ captureCampaignParams: () => ({ utms: {} }) }));

const originalFetch = globalThis.fetch;
beforeEach(() => { globalThis.fetch = vi.fn() as never; });
afterEach(() => { globalThis.fetch = originalFetch; vi.clearAllMocks(); });

function mockResponse(status: number, body: unknown) {
  (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

describe("subscribeEmail — dup-signal classification", () => {
  const opts = { source: "test", locale: "en" };

  it("new contact → success", async () => {
    mockResponse(200, { ok: true });
    expect(await subscribeEmail("new@example.com", opts)).toEqual({ kind: "success" });
  });

  it("resubscribed (was unsubscribed) → already", async () => {
    mockResponse(200, { ok: true, resubscribed: true });
    expect(await subscribeEmail("back@example.com", opts)).toEqual({ kind: "already" });
  });

  it("already_subscribed (still active) → already — the GAP-A regression", async () => {
    // Before the fix this returned `success`, replaying the celebration on
    // the default hero. Must be `already` so becomeFreeMember gets returning:true.
    mockResponse(200, { ok: true, already_subscribed: true });
    expect(await subscribeEmail("active@example.com", opts)).toEqual({ kind: "already" });
  });

  it("bad email (client-side regex) → invalid, no fetch", async () => {
    expect(await subscribeEmail("nope", opts)).toEqual({ kind: "invalid" });
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("429 → rate_limited", async () => {
    mockResponse(429, { error: "rate_limited" });
    expect(await subscribeEmail("x@example.com", opts)).toEqual({ kind: "rate_limited" });
  });

  it("server invalid_email → invalid", async () => {
    mockResponse(400, { error: "invalid_email" });
    expect(await subscribeEmail("x@example.com", opts)).toEqual({ kind: "invalid" });
  });

  it("network throw → error", async () => {
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("down"));
    expect(await subscribeEmail("x@example.com", opts)).toEqual({ kind: "error" });
  });
});
