// Wire web-vitals → PostHog. Reports LCP / INP / CLS / TTFB once each
// becomes finalisable for the page. PostHog auto-segments by route +
// device; we attach the route explicitly so dashboard segments line up
// with our SPA's perceived navigation (since it's not a real router yet).
//
// We import from "web-vitals/attribution" (rather than plain
// "web-vitals") so the LCP metric carries the Element + URL that
// triggered it. Without attribution we know LCP is slow but not
// *which element* is the LCP — making it impossible to tell from
// telemetry whether the Hero, a card photo, or hero text is the
// bottleneck. The attribution build is a tree-shake-friendly
// alternative; the bundle delta is ~1 KB.

import {
  onCLS,
  onINP,
  onLCP,
  onTTFB,
  type LCPMetricWithAttribution,
  type Metric,
} from "web-vitals/attribution";
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
      emitLcpAttribution(metric as LCPMetricWithAttribution);
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

// Attribution sidecar: lets PostHog tell us *which* DOM node was the
// LCP element. Useful when LCP is poor and we need to know whether
// it was the Hero photo, a card photo, or a text node. Some browsers
// don't populate the LCP entry (e.g. when the page closes before
// it's reported), in which case we just skip the emit.
function emitLcpAttribution(metric: LCPMetricWithAttribution) {
  const a = metric.attribution;
  const entry = a && a.lcpEntry;
  // The LCP element ref isn't always retained by the browser past
  // the LCP event itself — the Element field can be null when the
  // measurement was for an inline image already removed from the DOM.
  const el = entry && entry.element;
  if (!el) return;
  const tag = (el.tagName || "").toLowerCase() || "unknown";
  const cls = typeof el.className === "string" ? el.className.trim() : undefined;
  // For image LCP, `url` carries the resource URL — invaluable for
  // pinpointing which photo (hero, card, etc) won the LCP race.
  const url = a && typeof a.url === "string" && a.url ? a.url : undefined;
  track("web_vitals.lcp.attribution", {
    element_tag: tag,
    ...(cls ? { element_class: cls } : {}),
    ...(url ? { url } : {}),
    ms: metric.value,
  });
}

export function bootWebVitals() {
  onLCP(emit);
  onINP(emit);
  onCLS(emit);
  onTTFB(emit);
}
