// Unit tests for the Stripe webhook event-id dedup helpers in
// api/stripe/webhook.js. These cover the small pure surface — the
// pulpo_last_event_id read/write against subscription.metadata — that
// guards the anonymous_invitation_created path from double-firing
// createInvitation + sendActivationEmail on Stripe webhook retries.
//
// The full handler integration test would require mocking Clerk +
// Stripe + Resend end-to-end; those live as Sebas-side preview-URL
// smokes per CLAUDE.md. This file tests the dedup primitive only.

import { describe, it, expect, vi } from "vitest";

import {
  isStripeEventAlreadyProcessed,
  markStripeEventProcessed,
} from "../../api/stripe/webhook.js";

function mockStripe({ metadata = {}, retrieveThrows = false, updateThrows = false } = {}) {
  const updateCalls = [];
  return {
    subscriptions: {
      retrieve: vi.fn(async () => {
        if (retrieveThrows) throw new Error("stripe_unreachable");
        return { id: "sub_test", metadata };
      }),
      update: vi.fn(async (id, patch) => {
        updateCalls.push({ id, patch });
        if (updateThrows) throw new Error("stripe_write_failed");
        return { id, metadata: { ...metadata, ...patch.metadata } };
      }),
    },
    __updateCalls: updateCalls,
  };
}

describe("isStripeEventAlreadyProcessed", () => {
  it("returns true when subscription.metadata.pulpo_last_event_id matches", async () => {
    const stripe = mockStripe({ metadata: { pulpo_last_event_id: "evt_123" } });
    expect(await isStripeEventAlreadyProcessed(stripe, "sub_test", "evt_123")).toBe(true);
  });

  it("returns false when no metadata is present (first delivery)", async () => {
    const stripe = mockStripe({ metadata: {} });
    expect(await isStripeEventAlreadyProcessed(stripe, "sub_test", "evt_123")).toBe(false);
  });

  it("returns false when a different event.id was previously recorded", async () => {
    const stripe = mockStripe({ metadata: { pulpo_last_event_id: "evt_old" } });
    expect(await isStripeEventAlreadyProcessed(stripe, "sub_test", "evt_new")).toBe(false);
  });

  it("returns false on Stripe read failure (fail-open — duplicate is better than silent drop)", async () => {
    const stripe = mockStripe({ retrieveThrows: true });
    expect(await isStripeEventAlreadyProcessed(stripe, "sub_test", "evt_123")).toBe(false);
  });

  it("returns false when subscriptionId or eventId is missing", async () => {
    const stripe = mockStripe();
    expect(await isStripeEventAlreadyProcessed(stripe, "", "evt_123")).toBe(false);
    expect(await isStripeEventAlreadyProcessed(stripe, "sub_test", "")).toBe(false);
    expect(stripe.subscriptions.retrieve).not.toHaveBeenCalled();
  });
});

describe("markStripeEventProcessed", () => {
  it("writes pulpo_last_event_id to subscription metadata", async () => {
    const stripe = mockStripe();
    await markStripeEventProcessed(stripe, "sub_test", "evt_123");
    expect(stripe.subscriptions.update).toHaveBeenCalledOnce();
    expect(stripe.__updateCalls[0]).toEqual({
      id: "sub_test",
      patch: { metadata: { pulpo_last_event_id: "evt_123" } },
    });
  });

  it("swallows Stripe write failures (non-fatal — handler keeps the 200)", async () => {
    const stripe = mockStripe({ updateThrows: true });
    await expect(
      markStripeEventProcessed(stripe, "sub_test", "evt_123")
    ).resolves.toBeUndefined();
  });

  it("no-ops when subscriptionId or eventId is missing", async () => {
    const stripe = mockStripe();
    await markStripeEventProcessed(stripe, "", "evt_123");
    await markStripeEventProcessed(stripe, "sub_test", "");
    expect(stripe.subscriptions.update).not.toHaveBeenCalled();
  });
});

describe("dedup round-trip — write then read same event_id", () => {
  it("mark-then-check returns true (the retry scenario)", async () => {
    // Simulate the lifecycle: handler processes evt_123, marks it,
    // then Stripe retries the same event and the check short-circuits.
    let storedMetadata = {};
    const stripe = {
      subscriptions: {
        retrieve: vi.fn(async () => ({ id: "sub_test", metadata: storedMetadata })),
        update: vi.fn(async (id, patch) => {
          storedMetadata = { ...storedMetadata, ...patch.metadata };
          return { id, metadata: storedMetadata };
        }),
      },
    };
    // First delivery: not yet processed.
    expect(await isStripeEventAlreadyProcessed(stripe, "sub_test", "evt_123")).toBe(false);
    // Handler marks it.
    await markStripeEventProcessed(stripe, "sub_test", "evt_123");
    // Stripe retries: now skipped.
    expect(await isStripeEventAlreadyProcessed(stripe, "sub_test", "evt_123")).toBe(true);
  });

  it("a different event.id on the same subscription is NOT skipped", async () => {
    // Second purchase / second-month renewal carries a different event.id
    // — we want to process it normally, not treat it as a duplicate.
    let storedMetadata = { pulpo_last_event_id: "evt_old" };
    const stripe = {
      subscriptions: {
        retrieve: vi.fn(async () => ({ id: "sub_test", metadata: storedMetadata })),
        update: vi.fn(async () => ({})),
      },
    };
    expect(await isStripeEventAlreadyProcessed(stripe, "sub_test", "evt_new")).toBe(false);
  });
});
