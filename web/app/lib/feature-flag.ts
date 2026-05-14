// Feature-flag helpers for runtime kill-switch behavior. Thin layer over
// telemetry/client.ts's PostHog flag bridge.
//
// Two reads:
//   * `useFeatureFlag(key, fallback)` — React hook; re-renders once
//     PostHog flags load.
//   * `readFeatureFlag(key, fallback)` — sync read for non-React call
//     sites (event-handler bodies, util functions).
//
// URL-param escape hatch: `?ff_<key>=1` / `?ff_<key>=0` forces a value
// for the current page load. Used by Playwright specs to assert both
// branches without round-tripping the PostHog dashboard. Production
// traffic shouldn't carry these params; the allow-list in
// telemetry/client.ts already strips them from PostHog $current_url.
//
// Fallback semantics: pass the value you want when PostHog hasn't
// answered yet (cold load, declined consent, dev env without
// VITE_POSTHOG_KEY). For Wave-1 `cta_routing_v2`, fallback is `true` —
// new routing is the default; the flag exists only to disable it.

import { useEffect, useState } from "react";
import { isFeatureEnabled, onFeatureFlagsLoaded } from "../telemetry/client";

function readUrlOverride(key: string): boolean | null {
  if (typeof window === "undefined") return null;
  try {
    const v = new URLSearchParams(window.location.search).get(`ff_${key}`);
    if (v === "1") return true;
    if (v === "0") return false;
    return null;
  } catch {
    return null;
  }
}

export function readFeatureFlag(key: string, fallback: boolean): boolean {
  const override = readUrlOverride(key);
  if (override !== null) return override;
  return isFeatureEnabled(key, fallback);
}

export function useFeatureFlag(key: string, fallback: boolean): boolean {
  const [value, setValue] = useState<boolean>(() => readFeatureFlag(key, fallback));
  useEffect(() => {
    // Re-read once flags arrive. URL overrides win regardless, but a
    // second read is cheap and keeps the hook resilient if PostHog
    // finishes loading mid-render.
    const unsubscribe = onFeatureFlagsLoaded(() => {
      setValue(readFeatureFlag(key, fallback));
    });
    return unsubscribe;
  }, [key, fallback]);
  return value;
}
