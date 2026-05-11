// Asset-load telemetry — observe the static-asset chain that bootstraps
// the app and surface ms/bytes/cache-status to PostHog so we can verify
// our cache-control config end-to-end.
//
// Why this exists: the prior "Discover feels slow" investigations
// shipped four PRs without confirming the underlying cache behaviour
// from telemetry. After PR-185 fixed /photos and /data, the asset
// chain (entry bundle, dynamic chunks, CSS, category WebPs) was
// still serving with `max-age=0, must-revalidate`. We want PostHog to
// show this directly so the next regression is caught before users
// notice.
//
// Implementation: a PerformanceObserver subscribes to "resource"
// entries and filters to the Vite-built tree. For each match we emit
// `perf.asset_load` with kind/url/ms/bytes/cache. The observer also
// drains already-finished resources via getEntriesByType — those
// load before bootAssetTelemetry runs (it boots after React mount;
// the entry bundle has already finished by then).
//
// URL paths covered:
//   /build/*           — current Vite output (post PR-193, base="/"
//                        and assetsDir="build"). Hashed JS / CSS /
//                        category WebPs.
//   /preview/assets/*  — legacy path from before PR-193 dropped the
//                        /preview prefix. Matched for back-compat in
//                        case someone has a stale tab open right after
//                        the cutover.
//   /assets/*          — brand-asset namespace (favicon, logo SVG).
//                        No Vite-built JS lives here today; matched
//                        defensively in case the structure shifts.

import { track } from "./client";

type AssetKind = "entry" | "chunk" | "css" | "webp";

const ENTRY_FILENAMES = new Set(["index.js"]);

function classify(url: string): AssetKind | null {
  // Match Vite output across the /build/* (current), /preview/assets/*
  // (legacy / stale tabs), and /assets/* (brand-asset namespace) URL
  // shapes. Single regex — capture group is the filename.
  const m = url.match(/\/(?:build|preview\/assets|assets)\/([^/?#]+)/);
  if (!m) return null;
  const filename = m[1];
  if (filename.endsWith(".css")) return "css";
  if (filename.endsWith(".webp")) return "webp";
  if (filename.endsWith(".js")) {
    // Bundle is content-hashed (e.g. "index-abc123.js"). Treat
    // anything starting with "index" as the entry; the rest are
    // dynamically-imported chunks.
    if (
      ENTRY_FILENAMES.has(filename) ||
      filename.startsWith("index-") ||
      filename.startsWith("index.")
    ) {
      return "entry";
    }
    return "chunk";
  }
  return null;
}

// PerformanceResourceTiming has `transferSize`, `encodedBodySize`, and
// `deliveryType` (newer browsers). We use them to infer cache-state
// without needing access to response headers (which JS can't read for
// cross-origin requests anyway):
//
//   deliveryType === "cache"     → hit (Chrome 109+)
//   transferSize === 0 && body>0 → hit (served from disk/memory cache)
//   transferSize > 0             → miss (network response)
//   else                         → unknown (unusual; report so PostHog
//                                  can show the long tail)
function inferCache(entry: PerformanceResourceTiming): "hit" | "miss" | "unknown" {
  const dt = (entry as PerformanceResourceTiming & { deliveryType?: string }).deliveryType;
  if (dt === "cache") return "hit";
  if (entry.transferSize === 0 && entry.encodedBodySize > 0) return "hit";
  if (entry.transferSize > 0) return "miss";
  return "unknown";
}

function emitForEntry(entry: PerformanceResourceTiming) {
  const url = entry.name;
  const kind = classify(url);
  if (!kind) return;
  const ms = Math.round(entry.responseEnd - entry.startTime);
  const bytes = entry.encodedBodySize || entry.transferSize || 0;
  track("perf.asset_load", {
    kind,
    url,
    ms,
    bytes,
    cache: inferCache(entry),
  });
}

let booted = false;

export function bootAssetTelemetry() {
  if (booted) return;
  booted = true;
  if (typeof window === "undefined" || typeof PerformanceObserver === "undefined") return;
  // 1. Drain anything already finished. The entry bundle finishes
  //    before this function runs (it boots from app.jsx mount, by which
  //    time the bundle and CSS are long since loaded).
  try {
    const existing = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
    for (const e of existing) emitForEntry(e);
  } catch {
    // ignore — perf API can be partially blocked by some content-blockers
  }
  // 2. Subscribe for future entries (dynamic chunks loaded after mount,
  //    e.g. clerk-bundle, plus the category WebPs as they paint).
  try {
    const obs = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        emitForEntry(e as PerformanceResourceTiming);
      }
    });
    obs.observe({ type: "resource", buffered: false });
  } catch {
    // ignore — same reason as above
  }
}
