import { describe, expect, it, vi } from "vitest";
import {
  pollPortalReturnState,
  subscriptionRefreshSnapshot,
  subscriptionSnapshotChanged,
  type SubscriptionRefreshSnapshot,
} from "./portal-return-refresh";

describe("portal-return subscription refresh polling", () => {
  const active: SubscriptionRefreshSnapshot = {
    display: "active",
    cancel_at_period_end: false,
    subscription_status: "active",
    canceled_at: null,
  };
  const canceling: SubscriptionRefreshSnapshot = {
    display: "canceling",
    cancel_at_period_end: true,
    subscription_status: "active",
    canceled_at: null,
  };

  it("detects display/cancellation state changes", () => {
    expect(subscriptionSnapshotChanged(active, active)).toBe(false);
    expect(subscriptionSnapshotChanged(active, canceling)).toBe(true);
  });

  it("polls until the first detected state change", async () => {
    let current = active;
    const reloadUser = vi.fn(async () => {
      if (reloadUser.mock.calls.length === 2) current = canceling;
    });
    const wait = vi.fn(async () => {});

    const result = await pollPortalReturnState({
      initial: active,
      getSnapshot: () => current,
      reloadUser,
      wait,
      maxAttempts: 5,
      intervalMs: 1500,
    });

    expect(result.changed).toBe(true);
    expect(result.attempts).toBe(2);
    expect(result.waited_ms).toBe(3000);
    expect(result.from.display).toBe("active");
    expect(result.to.display).toBe("canceling");
    expect(reloadUser).toHaveBeenCalledTimes(2);
  });

  it("returns stale after five unchanged attempts", async () => {
    const reloadUser = vi.fn(async () => {});
    const wait = vi.fn(async () => {});

    const result = await pollPortalReturnState({
      initial: active,
      getSnapshot: () => active,
      reloadUser,
      wait,
      maxAttempts: 5,
      intervalMs: 1500,
    });

    expect(result.changed).toBe(false);
    expect(result.attempts).toBe(5);
    expect(result.waited_ms).toBe(7500);
    expect(reloadUser).toHaveBeenCalledTimes(5);
  });

  it("creates snapshots from derived subscription state", () => {
    expect(subscriptionRefreshSnapshot({
      display: "canceled",
      cancel_at_period_end: false,
      status: "canceled",
      canceled_at: 123,
    })).toEqual({
      display: "canceled",
      cancel_at_period_end: false,
      subscription_status: "canceled",
      canceled_at: 123,
    });
  });
});
