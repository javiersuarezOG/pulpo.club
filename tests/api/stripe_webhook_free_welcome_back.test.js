// Unit tests for the churned-Pro → Free welcome-back dispatch helper
// (fireFreeWelcomeBack) in api/stripe/webhook.js.
//
//   • POSTs the internal free dispatcher with variant=free_welcome_back,
//     source=stripe_downgrade, is_new_contact=true, locale forwarded.
//   • No PULPO_INTERNAL_TOKEN → skips cleanly, no fetch (no GH fallback —
//     a missed welcome-back is low-stakes, unlike the Pro activation email).
//   • fetch failure → best-effort {fired:false}, never throws.
//
// The terminal-branch dedup (downgrade_welcome_sub_id) + the removal of the
// cancel-time unsubscribe are asserted in resend_audience_sync_shape.test.js;
// full webhook integration is the Sebas-side Stripe-sandbox dry-run.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { fireFreeWelcomeBack } from "../../api/stripe/webhook.js";

function mockFetch({ status = 200, body = { status: "sent", dry_run: true }, throws = false } = {}) {
  return vi.fn(async () => {
    if (throws) throw new Error("network_unreachable");
    return { status, json: async () => body };
  });
}

describe("fireFreeWelcomeBack — churned-Pro welcome-back", () => {
  const ORIG = process.env.PULPO_INTERNAL_TOKEN;
  beforeEach(() => { process.env.PULPO_INTERNAL_TOKEN = "tok_test"; });
  afterEach(() => {
    if (ORIG === undefined) delete process.env.PULPO_INTERNAL_TOKEN;
    else process.env.PULPO_INTERNAL_TOKEN = ORIG;
    vi.restoreAllMocks();
  });

  it("POSTs the free endpoint with the right variant/source/payload", async () => {
    const fetchImpl = mockFetch();
    const r = await fireFreeWelcomeBack({
      email: "churn@example.com", locale: "es", source: "stripe_downgrade",
      distinctId: "d", t0: Date.now(), fetchImpl, internalBaseUrl: "https://pulpo.test",
    });
    expect(r.fired).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://pulpo.test/api/internal/free-welcome-send");
    expect(opts.headers.Authorization).toBe("Bearer tok_test");
    const payload = JSON.parse(opts.body);
    expect(payload).toMatchObject({
      email: "churn@example.com",
      variant: "free_welcome_back",
      source: "stripe_downgrade",
      locale: "es",
      is_new_contact: true,
    });
  });

  it("no PULPO_INTERNAL_TOKEN → skips, no fetch (no GH fallback)", async () => {
    delete process.env.PULPO_INTERNAL_TOKEN;
    const fetchImpl = mockFetch();
    const r = await fireFreeWelcomeBack({
      email: "x@example.com", fetchImpl, internalBaseUrl: "https://pulpo.test",
    });
    expect(r.fired).toBe(false);
    expect(r.reason).toBe("internal_token_unset");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("fetch failure → best-effort {fired:false}, never throws", async () => {
    const fetchImpl = mockFetch({ throws: true });
    const r = await fireFreeWelcomeBack({
      email: "x@example.com", distinctId: "d", t0: Date.now(),
      fetchImpl, internalBaseUrl: "https://pulpo.test",
    });
    expect(r.fired).toBe(false);
    expect(r.reason).toMatch(/fetch_failed/);
  });
});
