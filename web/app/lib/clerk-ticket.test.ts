import { describe, expect, it, vi } from "vitest";
import { consumeTicketWithRetry } from "./clerk-ticket";

describe("consumeTicketWithRetry", () => {
  it("retries sdk_not_ready and returns the later success", async () => {
    const consumeTicket = vi.fn()
      .mockResolvedValueOnce({ ok: false, code: "sdk_not_ready", message: "Clerk SDK not ready" })
      .mockResolvedValueOnce({ ok: true, status: "missing_requirements", emailAddress: "test@pulpo.club" });
    const retries: unknown[] = [];

    const result = await consumeTicketWithRetry(consumeTicket, "ticket_123", {
      initialDelayMs: 0,
      onRetry: (event) => retries.push(event),
    });

    expect(result).toMatchObject({ ok: true, status: "missing_requirements" });
    expect(consumeTicket).toHaveBeenCalledTimes(2);
    expect(retries).toEqual([
      { attempt: 1, code: "sdk_not_ready", message: "Clerk SDK not ready" },
    ]);
  });

  it("does not retry terminal ticket errors", async () => {
    const consumeTicket = vi.fn()
      .mockResolvedValueOnce({ ok: false, code: "ticket_invalid", message: "Ticket is invalid" });

    const result = await consumeTicketWithRetry(consumeTicket, "ticket_123", {
      initialDelayMs: 0,
    });

    expect(result).toMatchObject({ ok: false, code: "ticket_invalid" });
    expect(consumeTicket).toHaveBeenCalledTimes(1);
  });

  it("stops after max sdk_not_ready attempts", async () => {
    const consumeTicket = vi.fn()
      .mockResolvedValue({ ok: false, code: "sdk_not_ready", message: "Still booting" });
    const retries: unknown[] = [];

    const result = await consumeTicketWithRetry(consumeTicket, "ticket_123", {
      maxAttempts: 3,
      initialDelayMs: 0,
      onRetry: (event) => retries.push(event),
    });

    expect(result).toMatchObject({ ok: false, code: "sdk_not_ready" });
    expect(consumeTicket).toHaveBeenCalledTimes(3);
    expect(retries).toHaveLength(2);
  });
});
