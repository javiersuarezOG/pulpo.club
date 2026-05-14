// Wave-5: trigger logic for the USP popup. Pure-ish module that owns
// the decision of "should the popup fire right now, and from what
// trigger?" Side effects (event listeners, timers) are explicit and
// teardown-aware so the consuming component can arm + disarm cleanly.
//
// Four trigger types:
//   * url_param   — `?upsell=1` on the URL. Fires synchronously on
//                   arm; no listeners required.
//   * scroll      — fires when window.scrollY / scrollable height
//                   crosses SCROLL_THRESHOLD.
//   * timer       — fires after TIMER_MS on the page.
//   * exit_intent — desktop only (window.innerWidth >= 1024). Fires
//                   when the pointer leaves the top of the viewport
//                   (mouseleave with clientY <= 0).
//
// First trigger to fire wins; the rest disarm. After dismissal the
// 7-day cap activates, mirroring the existing ProUpsellModal pattern.
//
// Paid users and dismissed users are filtered at the arm step — the
// triggers never wire if either condition matches.

import { tierFor, type GatingUser } from "./gating";

export type UspTrigger = "url_param" | "scroll" | "timer" | "exit_intent";

const SUPPRESSION_DAYS = 7;
const SCROLL_THRESHOLD = 0.5;     // 50% of scrollable height
const TIMER_MS = 30_000;          // 30s on page
const EXIT_INTENT_MIN_WIDTH = 1024; // desktop only

export const USP_DISMISSED_AT_KEY = "pulpo-usp-popup-dismissed-at";

export function markUspPopupDismissed(now?: number): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(USP_DISMISSED_AT_KEY, String(now || Date.now()));
  } catch {
    // localStorage unavailable (private mode + restrictive browser);
    // accept the cost of re-showing on next visit.
  }
}

export function isWithinSuppressionWindow(now: number = Date.now()): boolean {
  if (typeof localStorage === "undefined") return false;
  try {
    const dismissedAt = parseInt(localStorage.getItem(USP_DISMISSED_AT_KEY) || "", 10);
    if (!Number.isFinite(dismissedAt)) return false;
    const ageMs = now - dismissedAt;
    const windowMs = SUPPRESSION_DAYS * 24 * 3600 * 1000;
    return ageMs >= 0 && ageMs < windowMs;
  } catch {
    return false;
  }
}

// Pre-arm gate. Returns the URL-param trigger immediately if it fires
// on this load; null if the popup shouldn't show at all; an "arm"
// signal if listeners should be wired for scroll / timer / exit-intent.
export type ArmDecision =
  | { kind: "fire_now"; trigger: "url_param" }
  | { kind: "arm" }
  | { kind: "skip"; reason: "paid_user" | "suppressed" | "force_off" | "ssr" };

export type ArmContext = {
  user: GatingUser;
  // Injection points for tests; in prod these read window/Date.
  searchParams?: URLSearchParams;
  now?: number;
};

export function decideArm(ctx: ArmContext): ArmDecision {
  // SSR + non-browser environments: never arm. The caller's mount
  // effect will re-call us client-side.
  if (typeof window === "undefined" && !ctx.searchParams) {
    return { kind: "skip", reason: "ssr" };
  }

  // Paid users never see the USP popup — they already converted.
  const tier = tierFor(ctx.user);
  if (tier === "pro" || tier === "agency") {
    return { kind: "skip", reason: "paid_user" };
  }

  // 7-day suppression after dismissal. Sits BEFORE URL-param so a
  // freshly-dismissed user clicking a `?upsell=1` link doesn't get
  // re-prompted — explicit force-off (?upsell=0) handled below.
  if (isWithinSuppressionWindow(ctx.now)) {
    return { kind: "skip", reason: "suppressed" };
  }

  const params = ctx.searchParams || (() => {
    try { return new URLSearchParams(window.location.search); }
    catch { return new URLSearchParams(""); }
  })();

  // Explicit force-off wins over everything else (including suppression
  // — but we already returned `suppressed` above if it would fire).
  if (params.get("upsell") === "0") {
    return { kind: "skip", reason: "force_off" };
  }

  // Explicit force-on fires immediately on mount.
  if (params.get("upsell") === "1") {
    return { kind: "fire_now", trigger: "url_param" };
  }

  // No URL signal — arm the passive triggers.
  return { kind: "arm" };
}

// Wire scroll / timer / exit-intent. Returns a teardown function that
// disarms every listener. The first trigger to fire calls onFire() and
// auto-disarms via the teardown so subsequent triggers don't double-fire.
export function armPassiveTriggers(
  onFire: (trigger: Exclude<UspTrigger, "url_param">) => void,
): () => void {
  if (typeof window === "undefined") return () => {};

  let fired = false;
  const teardowns: Array<() => void> = [];

  const fire = (trigger: Exclude<UspTrigger, "url_param">) => {
    if (fired) return;
    fired = true;
    teardowns.forEach((fn) => { try { fn(); } catch { /* ignore */ } });
    onFire(trigger);
  };

  // ── Scroll trigger ────────────────────────────────────────────────
  const onScroll = () => {
    const scrollable = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const progress = window.scrollY / scrollable;
    if (progress >= SCROLL_THRESHOLD) fire("scroll");
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  teardowns.push(() => window.removeEventListener("scroll", onScroll));

  // ── Timer trigger ─────────────────────────────────────────────────
  const timerId = window.setTimeout(() => fire("timer"), TIMER_MS);
  teardowns.push(() => window.clearTimeout(timerId));

  // ── Exit-intent trigger (desktop only) ────────────────────────────
  if (window.innerWidth >= EXIT_INTENT_MIN_WIDTH) {
    const onMouseLeave = (e: MouseEvent) => {
      if (e.clientY <= 0) fire("exit_intent");
    };
    document.addEventListener("mouseleave", onMouseLeave);
    teardowns.push(() => document.removeEventListener("mouseleave", onMouseLeave));
  }

  return () => {
    fired = true; // block any in-flight callbacks from re-entering
    teardowns.forEach((fn) => { try { fn(); } catch { /* ignore */ } });
  };
}

// Test-only exports. Importing these in production is fine — they're
// constants used by the runtime — but the names exist so spec files
// don't drift if the values change.
export const _TESTING = {
  SUPPRESSION_DAYS,
  SCROLL_THRESHOLD,
  TIMER_MS,
  EXIT_INTENT_MIN_WIDTH,
};
