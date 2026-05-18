// Shared Stripe-checkout-from-modal helper. Used by ProUpsellModal
// (campaign-triggered) and FreeMonthModal (click-triggered) to avoid
// duplicating the postCheckout / soft-fail-on-bad-promo-code retry /
// rate-limited handling / api.error track / window.location.assign
// pattern across two modal surfaces. A fix in one place lands for both.
//
// Why a helper rather than a hook: the only state is "submitting", which
// each modal manages with its own useState (different button copy/etc).
// The async logic doesn't depend on React lifecycle, so a plain async
// function keeps the surface small and unit-test-friendly.

import { track, getDistinctId } from "../telemetry/hook";

export type StartCheckoutInput = {
  // Locale forwarded to the server so the Stripe success/cancel URLs
  // and email copy land in the visitor's language.
  locale: string;
  // Campaign UTMs from useCampaignParams(). Spread into the POST body
  // exactly like ProUpsellModal already does — preserved attribution.
  utms?: Record<string, string>;
  // ?code=… from the URL. When present, the server pre-applies the
  // promotion code on the Stripe session via discounts:[]. If invalid,
  // we soft-retry without the code so the visitor still reaches Stripe.
  urlCode?: string | null;
};

export type StartCheckoutResult =
  | { kind: "redirect"; url: string }
  | { kind: "rate_limited" }
  | { kind: "error"; reason: string };

async function postCheckout(input: StartCheckoutInput, includeCode: boolean): Promise<Response> {
  return fetch("/api/stripe/start-checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      promoCode: includeCode && input.urlCode ? input.urlCode : null,
      locale: input.locale,
      // posthog_anon_id stitches the anon session → email-derived
      // person_id on the server side (webhook.js calls posthog.alias()
      // with this value). Without it, the funnel breaks at checkout
      // completion. null when telemetry SDK hasn't loaded yet —
      // server tolerates absence.
      posthog_anon_id: getDistinctId(),
      ...(input.utms || {}),
    }),
  });
}

export async function startCheckoutFromModal(input: StartCheckoutInput): Promise<StartCheckoutResult> {
  try {
    let res = await postCheckout(input, true);
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      const reason = detail && (detail as { error?: string }).error;

      if (reason === "invalid_promo_code" && input.urlCode) {
        // Soft-fail on a bad code: drop it and retry once. The visitor
        // never sees a dead-end on a broken Reddit/Twitter link.
        res = await postCheckout(input, false);
        if (!res.ok) {
          const detail2 = await res.json().catch(() => ({}));
          const reason2 = detail2 && (detail2 as { error?: string }).error;
          track("api.error", {
            endpoint: "/api/stripe/start-checkout",
            status: res.status,
            reason: reason2,
            detail: (detail2 as { detail?: string }).detail,
          });
          return { kind: "error", reason: reason2 ?? "unknown" };
        }
      } else if (reason === "rate_limited") {
        return { kind: "rate_limited" };
      } else {
        track("api.error", {
          endpoint: "/api/stripe/start-checkout",
          status: res.status,
          reason,
          detail: (detail as { detail?: string }).detail,
        });
        return { kind: "error", reason: reason ?? "unknown" };
      }
    }

    const data = (await res.json()) as { url?: string };
    if (!data || !data.url) {
      return { kind: "error", reason: "missing_url" };
    }
    return { kind: "redirect", url: data.url };
  } catch (err) {
    track("api.error", {
      endpoint: "/api/stripe/start-checkout",
      status: 0,
      reason: "network",
      detail: err && (err as Error).message,
    });
    return { kind: "error", reason: "network" };
  }
}
