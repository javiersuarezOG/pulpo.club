// Real-user monitoring (PRD P2-6, PR-5B-B).
//
// Reports Core Web Vitals (LCP, CLS, INP) to PostHog via the existing
// track() helper. Loaded lazily so first-paint cost is unaffected; the
// web-vitals library is ~3 kB gz on its own and the report only fires
// after the page has settled.
//
// Sampling
//   - 100% on / (home), /browse, /start — high-traffic acquisition surfaces
//     where we need every data point for P75/P95 confidence.
//   - 25% elsewhere — bound PostHog ingest while still detecting
//     regressions on /listing, /account, /plans, /admin, etc.
//
// Route bucketing
//   The "route" property is a coarse path category, NOT the full URL.
//   Avoids high-cardinality breakdowns (e.g. /listing/<id> would create
//   one cohort per listing). Dashboards group on `route` + `rating`.

import { track } from "./client";

type Rating = "good" | "needs-improvement" | "poor";

interface Metric {
  value: number;
  rating: Rating;
  id: string;
}

const HIGH_TRAFFIC_ROUTES = new Set(["/", "/browse", "/start"]);
const ELSEWHERE_SAMPLE_RATE = 0.25;

function classifyRoute(pathname: string): string {
  if (pathname === "/" || pathname === "") return "/";
  if (pathname.startsWith("/browse")) return "/browse";
  if (pathname.startsWith("/start")) return "/start";
  if (pathname.startsWith("/listing")) return "/listing";
  if (pathname.startsWith("/account")) return "/account";
  if (pathname.startsWith("/plans")) return "/plans";
  if (pathname.startsWith("/admin")) return "/admin";
  if (pathname.startsWith("/saved")) return "/saved";
  return "other";
}

function shouldSample(route: string): boolean {
  if (HIGH_TRAFFIC_ROUTES.has(route)) return true;
  return Math.random() < ELSEWHERE_SAMPLE_RATE;
}

function currentLocale(): string {
  try {
    if (typeof localStorage !== "undefined") {
      const stored = localStorage.getItem("pulpo-locale");
      if (stored === "en" || stored === "es") return stored;
    }
  } catch {
    // Ignore — locale defaults below.
  }
  return "en";
}

// Each metric fires at most once per pageload but web-vitals may
// re-deliver LCP if a later, larger element supersedes the previous
// candidate. We dedupe in PostHog via the `id` property; here we
// simply forward every call so the latest value wins per pageload.
function report(eventName: "rum.lcp" | "rum.cls" | "rum.inp", metric: Metric) {
  const route = classifyRoute(typeof window !== "undefined" ? window.location.pathname : "/");
  if (!shouldSample(route)) return;
  try {
    track(eventName, {
      value: metric.value,
      rating: metric.rating,
      route,
      locale: currentLocale(),
      id: metric.id,
    });
  } catch {
    // Telemetry must never throw into the host page.
  }
}

let initialized = false;

export function initRUM(): void {
  if (initialized) return;
  if (typeof window === "undefined") return;
  initialized = true;
  // Dynamic import keeps web-vitals out of the entry chunk. The library
  // itself defers all measurements behind PerformanceObserver, so the
  // import latency does not affect what we measure.
  import("web-vitals")
    .then(({ onLCP, onCLS, onINP }) => {
      onLCP((m) => report("rum.lcp", m));
      onCLS((m) => report("rum.cls", m));
      onINP((m) => report("rum.inp", m));
    })
    .catch(() => {
      // If the chunk fails to load we accept silent zero coverage rather
      // than producing a noisy exception in production.
    });
}
