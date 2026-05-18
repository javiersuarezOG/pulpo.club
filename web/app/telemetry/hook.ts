// useTelemetry — components import { track, identify } from this hook
// rather than the underlying client, so swapping out PostHog later is a
// one-file change.

import { useCallback } from "react";
import { track as rawTrack, identify as rawIdentify, resetIdentity } from "./client";
import type { EventMap, EventName } from "./events";

export function useTelemetry() {
  const track = useCallback(<K extends EventName>(name: K, props: EventMap[K]) => {
    rawTrack(name, props);
  }, []);

  const identify = useCallback((id: string, props?: Record<string, unknown>) => {
    rawIdentify(id, props);
  }, []);

  const reset = useCallback(() => {
    resetIdentity();
  }, []);

  return { track, identify, reset };
}

export { track, identify, resetIdentity, optIn, optOut, getDistinctId } from "./client";
