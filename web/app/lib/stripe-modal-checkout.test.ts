// Unit tests for the shared Stripe-checkout-from-modal helper. Mocks
// fetch + telemetry so the postCheckout / soft-fail-on-bad-code retry /
// rate-limited / network-error chain is exercised without a real
// Stripe round-trip.
//
// Both ProUpsellModal and FreeMonthModal depend on these branches.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { startCheckoutFromModal } from "./stripe-modal-checkout";

vi.mock("../telemetry/hook", () => ({
  track: vi.fn(),
  getDistinctId: () => "test-anon-id",
}));

const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = vi.fn() as never;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.clearAllMocks();
});

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("startCheckoutFromModal — happy path", () => {
  it("returns the Stripe redirect URL on 200", async () => {
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(200, { url: "https://checkout.stripe.com/c/pay/cs_test_123" }),
    );
    const result = await startCheckoutFromModal({ locale: "en" });
    expect(result).toEqual({
      kind: "redirect",
      url: "https://checkout.stripe.com/c/pay/cs_test_123",
    });
  });

  it("posts posthog_anon_id in the request body", async () => {
    const fetchMock = globalThis.fetch as never as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { url: "https://x" }));
    await startCheckoutFromModal({ locale: "es" });
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(init.body);
    expect(body.posthog_anon_id).toBe("test-anon-id");
    expect(body.locale).toBe("es");
  });

  it("returns error on missing url in response", async () => {
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(200, {}),
    );
    const result = await startCheckoutFromModal({ locale: "en" });
    expect(result).toEqual({ kind: "error", reason: "missing_url" });
  });
});

describe("startCheckoutFromModal — invalid_promo_code soft retry", () => {
  it("retries without the code when the first call rejects it", async () => {
    const fetchMock = globalThis.fetch as never as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(400, { error: "invalid_promo_code" }))
      .mockResolvedValueOnce(jsonResponse(200, { url: "https://retry.ok" }));
    const result = await startCheckoutFromModal({ locale: "en", urlCode: "BAD" });
    expect(result).toEqual({ kind: "redirect", url: "https://retry.ok" });
    // First call included the code; second call dropped it.
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).promoCode).toBe("BAD");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).promoCode).toBe(null);
  });

  it("returns error if the retry also fails", async () => {
    const fetchMock = globalThis.fetch as never as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(400, { error: "invalid_promo_code" }))
      .mockResolvedValueOnce(jsonResponse(500, { error: "server_down" }));
    const result = await startCheckoutFromModal({ locale: "en", urlCode: "BAD" });
    expect(result).toEqual({ kind: "error", reason: "server_down" });
  });
});

describe("startCheckoutFromModal — rate_limited", () => {
  it("returns rate_limited (without firing api.error)", async () => {
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(429, { error: "rate_limited" }),
    );
    const result = await startCheckoutFromModal({ locale: "en" });
    expect(result).toEqual({ kind: "rate_limited" });
  });
});

describe("startCheckoutFromModal — error paths", () => {
  it("returns error on non-promo-code 4xx/5xx", async () => {
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(500, { error: "internal" }),
    );
    const result = await startCheckoutFromModal({ locale: "en" });
    expect(result).toEqual({ kind: "error", reason: "internal" });
  });

  it("returns error on network failure", async () => {
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("connection refused"),
    );
    const result = await startCheckoutFromModal({ locale: "en" });
    expect(result).toEqual({ kind: "error", reason: "network" });
  });
});
