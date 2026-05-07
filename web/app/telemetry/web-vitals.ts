// Wire web-vitals → PostHog. Reports LCP / INP / CLS / TTFB once each
// becomes finalisable for the page. PostHog auto-segments by route +
// device; we attach the route explicitly so dashboard segments line up
// with our SPA's perceived navigation (since it's not a real router yet).

import { onCLS, onINP, onLCP, onTTFB, type Metric } from "web-vitals";
import { track } from "./client";

function rating(name: string, value: number): "good" | "needs-improvement" | "poor" {
  // Thresholds from web.dev/vitals/. Conservative — we want to know
  // when we're slipping out of "good".
  switch (name) {
    case "LCP":
      if (value <= 2500) return "good";
      if (value <= 4000) return "needs-improvement";
      return "poor";
    case "INP":
      if (value <= 200) return "good";
      if (value <= 500) return "needs-improvement";
      return "poor";
    case "CLS":
      if (value <= 0.1) return "good";
      if (value <= 0.25) return "needs-improvement";
      return "poor";
    case "TTFB":
      if (value <= 800) return "good";
      if (value <= 1800) return "needs-improvement";
      return "poor";
    default:
      return "good";
  }
}

function currentRoute(): string {
  if (typeof window === "undefined") return "/";
  return window.location.pathname || "/";
}

function emit(metric: Metric) {
  const r = rating(metric.name, metric.value);
  switch (metric.name) {
    case "LCP":
      track("web_vitals.lcp", { value: metric.value, rating: r, route: currentRoute() });
      return;
    case "INP":
      track("web_vitals.inp", { value: metric.value, rating: r, route: currentRoute() });
      return;
    case "CLS":
      track("web_vitals.cls", { value: metric.value, rating: r, route: currentRoute() });
      return;
    case "TTFB":
      track("web_vitals.ttfb", { value: metric.value, rating: r, route: currentRoute() });
      return;
  }
}

export function bootWebVitals() {
  onLCP(emit);
  onINP(emit);
  onCLS(emit);
  onTTFB(emit);
}
