// Single config knob for the Pulpo Pro upsell popup on the home page.
//
// Flip `showForDirectTraffic` to `true` to show the popup to organic /
// direct visitors with no campaign params. Default `false` keeps the
// home page clean for SEO + return-visit traffic — only campaign-driven
// visitors see the upsell.
//
// `?upsell=1` and `?upsell=0` URL params override the auto-trigger
// per-link (per campaign). `?upsell=0` always wins; `?upsell=1` overrides
// the no-params case but never overrides `?upsell=0`.
//
// `campaignParams` is the set of URL params that count as a "campaign
// signal" — any one of them triggers the popup unless overridden.
// Add to the list to extend (e.g. `gclid`, `fbclid`, `ref`) without
// touching the trigger logic itself.
//
// Suppression: once the user dismisses the modal, suppress re-show for
// `suppressionDays`. Set 0 to disable suppression (popup re-fires on
// every campaign-tagged visit until the user converts).

export type UpsellConfig = {
  showForDirectTraffic: boolean;
  suppressionDays: number;
  campaignParams: readonly string[];
};

export const UPSELL_CONFIG: UpsellConfig = {
  showForDirectTraffic: false,
  suppressionDays: 7,
  campaignParams: ["utm_source", "utm_medium", "utm_campaign", "code"],
};

// localStorage key for the suppression timestamp. Per-device; not synced
// across browsers / a private window.
export const UPSELL_DISMISSED_AT_KEY = "pulpo-upsell-dismissed-at";

type DecideArgs = {
  searchParams: URLSearchParams;
  isProUser: boolean;
  now?: number; // injectable for tests
};

export type UpsellTrigger = "utm" | "code" | "explicit" | "direct" | null;

export type UpsellDecision =
  | { show: false; reason: "pro_user" | "force_off" | "suppressed" | "no_campaign_signal" }
  | { show: true; trigger: Exclude<UpsellTrigger, null> };

// Pure decision function — input the URL params + user state, output
// the show/no-show verdict plus the trigger label for telemetry.
// Per truth table in the plan; one source of truth so HomePage + tests
// agree.
export function decideShouldShowUpsell(args: DecideArgs): UpsellDecision {
  const { searchParams, isProUser, now } = args;
  // Pro users never see it — they already paid.
  if (isProUser) return { show: false, reason: "pro_user" };

  // Explicit force-off wins over everything else.
  const upsellFlag = searchParams.get("upsell");
  if (upsellFlag === "0") return { show: false, reason: "force_off" };

  // 7-day suppression after a prior dismissal.
  if (UPSELL_CONFIG.suppressionDays > 0 && typeof localStorage !== "undefined") {
    try {
      const dismissedAt = parseInt(localStorage.getItem(UPSELL_DISMISSED_AT_KEY) || "", 10);
      if (Number.isFinite(dismissedAt)) {
        const ageMs = (now || Date.now()) - dismissedAt;
        const windowMs = UPSELL_CONFIG.suppressionDays * 24 * 3600 * 1000;
        if (ageMs >= 0 && ageMs < windowMs) {
          return { show: false, reason: "suppressed" };
        }
      }
    } catch {
      // localStorage unavailable (private mode + restrictive browser);
      // fall through and treat as not-suppressed.
    }
  }

  // Explicit force-on for campaigns without utm tagging.
  if (upsellFlag === "1") return { show: true, trigger: "explicit" };

  // Campaign-param trigger — any of the configured params present.
  const hasCode = !!searchParams.get("code");
  if (hasCode) return { show: true, trigger: "code" };
  const hasUtm = UPSELL_CONFIG.campaignParams
    .filter((k) => k !== "code")
    .some((k) => !!searchParams.get(k));
  if (hasUtm) return { show: true, trigger: "utm" };

  // No signal — direct traffic. Honour the config knob.
  if (UPSELL_CONFIG.showForDirectTraffic) return { show: true, trigger: "direct" };
  return { show: false, reason: "no_campaign_signal" };
}

// Convenience: stamp the dismissal so subsequent visits respect
// suppressionDays. Called by the modal's dismiss handlers.
export function markUpsellDismissed(now?: number): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(UPSELL_DISMISSED_AT_KEY, String(now || Date.now()));
  } catch {
    // localStorage unavailable — accept the cost of re-showing the modal.
  }
}
