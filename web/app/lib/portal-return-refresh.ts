export type SubscriptionRefreshSnapshot = {
  display: string;
  cancel_at_period_end: boolean;
  subscription_status: string;
  canceled_at: number | null;
};

export type PortalReturnPollResult = {
  changed: boolean;
  attempts: number;
  waited_ms: number;
  from: SubscriptionRefreshSnapshot;
  to: SubscriptionRefreshSnapshot;
};

export function subscriptionRefreshSnapshot(subState: {
  display: string;
  cancel_at_period_end: boolean;
  status: string;
  canceled_at: number | null;
}): SubscriptionRefreshSnapshot {
  return {
    display: subState.display,
    cancel_at_period_end: subState.cancel_at_period_end,
    subscription_status: subState.status,
    canceled_at: subState.canceled_at,
  };
}

export function subscriptionSnapshotChanged(
  from: SubscriptionRefreshSnapshot,
  to: SubscriptionRefreshSnapshot,
): boolean {
  return from.display !== to.display
    || from.cancel_at_period_end !== to.cancel_at_period_end
    || from.subscription_status !== to.subscription_status
    || from.canceled_at !== to.canceled_at;
}

export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function pollPortalReturnState({
  initial,
  getSnapshot,
  reloadUser,
  wait = delay,
  maxAttempts = 5,
  intervalMs = 1500,
}: {
  initial: SubscriptionRefreshSnapshot;
  getSnapshot: () => SubscriptionRefreshSnapshot;
  reloadUser?: () => Promise<unknown> | unknown;
  wait?: (ms: number) => Promise<unknown>;
  maxAttempts?: number;
  intervalMs?: number;
}): Promise<PortalReturnPollResult> {
  let attempts = 0;
  let current = getSnapshot();
  while (attempts < maxAttempts) {
    attempts += 1;
    if (reloadUser) await reloadUser();
    await wait(intervalMs);
    current = getSnapshot();
    if (subscriptionSnapshotChanged(initial, current)) {
      return {
        changed: true,
        attempts,
        waited_ms: attempts * intervalMs,
        from: initial,
        to: current,
      };
    }
  }
  return {
    changed: false,
    attempts,
    waited_ms: attempts * intervalMs,
    from: initial,
    to: current,
  };
}
