// Shared campaign-param plumbing for /start AND the home-page
// <ProUpsellModal>. Both surfaces capture UTMs into sessionStorage,
// surface `?code=` to the checkout endpoint, and check whether the
// visitor came from a campaign link vs direct traffic.
//
// Lifting this into a single module avoids the two surfaces drifting
// (e.g. /start adding a new utm key while the home page popup misses
// it). One source of truth.

import { useEffect, useMemo, useState } from "react";

export const UTM_KEYS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_term",
  "utm_content",
] as const;

export type UtmKey = (typeof UTM_KEYS)[number];
export type Utms = Partial<Record<UtmKey, string>>;

export type CampaignParams = {
  /** The raw URL `?code=…` value, uppercased + trimmed. Empty when absent. */
  urlCode: string;
  /** All five UTMs from the current URL OR (fallback) from sessionStorage
   *  if the same browser visited a campaign URL earlier in the session. */
  utms: Utms;
  /** True when the URL carries `?cancelled=1` — the user came back from
   *  a Stripe Checkout they chose not to complete. */
  isCancelled: boolean;
  /** Optional explicit upsell override. `1` force-show, `0` force-hide,
   *  `null` defer to the auto-trigger logic. */
  upsellOverride: "1" | "0" | null;
};

const SS_KEY_PREFIX = "pulpo-";

// Read URL → capture into sessionStorage → return a normalized snapshot.
// Memoized at the component level via useCampaignParams() below.
export function captureCampaignParams(): CampaignParams {
  if (typeof window === "undefined") {
    return { urlCode: "", utms: {}, isCancelled: false, upsellOverride: null };
  }
  let params: URLSearchParams;
  try {
    params = new URLSearchParams(window.location.search);
  } catch {
    return { urlCode: "", utms: {}, isCancelled: false, upsellOverride: null };
  }

  const utms: Utms = {};
  for (const k of UTM_KEYS) {
    const v = params.get(k);
    if (v) {
      utms[k] = v;
      try { sessionStorage.setItem(SS_KEY_PREFIX + k, v); } catch { /* ignore */ }
    } else {
      try {
        const cached = sessionStorage.getItem(SS_KEY_PREFIX + k);
        if (cached) utms[k] = cached;
      } catch { /* ignore */ }
    }
  }

  const rawCode = params.get("code");
  const urlCode = rawCode ? rawCode.trim().toUpperCase() : "";
  const isCancelled = params.get("cancelled") === "1";
  const upsellFlag = params.get("upsell");
  const upsellOverride: "1" | "0" | null =
    upsellFlag === "1" ? "1" : upsellFlag === "0" ? "0" : null;

  return { urlCode, utms, isCancelled, upsellOverride };
}

// React hook — captures campaign params once per mount + persists.
// Both /start and the home-page <ProUpsellModal> consume this.
export function useCampaignParams(): CampaignParams {
  // Capture happens synchronously on first render — the values don't
  // change for the rest of the mount. useMemo with an empty deps array
  // (intentional — we never want to re-capture on subsequent renders
  // even if some other state changes the URL).
  return useMemo(() => captureCampaignParams(), []);
}

// Reflect a campaign param's *current* URL value into state, with a
// reactive update when the URL changes via pushState/replaceState/popstate.
// Used by the upsell-trigger decision in HomePage so dismissals (which
// stripState the upsell param) propagate without a remount.
export function useUrlParam(name: string): string | null {
  const read = () => {
    if (typeof window === "undefined") return null;
    try {
      return new URLSearchParams(window.location.search).get(name);
    } catch {
      return null;
    }
  };
  const [val, setVal] = useState<string | null>(read);
  useEffect(() => {
    const onPop = () => setVal(read());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
    // No deps — the read closure references no external mutable values.
  }, []);
  return val;
}
