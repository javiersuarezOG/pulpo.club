// Card-impression batching — fires `browse.card_impression` once per
// listing per page-view when a card crosses 50% visibility.
//
// Why a shared module instead of an observer per card: the browse grid
// can hold ~1500 listings. One IntersectionObserver watching every
// registered card element is far cheaper than 1500 observers, and
// batching many impressions into one PostHog event keeps us well under
// the EU free-tier event budget at scroll velocity.
//
// Dedupe: `${surface}:${listing_id}` fires at most once until
// resetImpressions(surface) is called — the list surfaces call that when
// their result set identity changes (sort/filter change), because the
// same listing re-entering the viewport under a NEW sort is a new
// impression worth counting.
//
// Consumers of the event: goals/ranking-relevance (CTR@20) and
// goals/image-quality (hero CTR). See web/app/telemetry/events.ts.

import { useCallback, useRef } from "react";
import { track } from "../telemetry/hook";

export type ImpressionSurface = "browse" | "saved" | "similar";

export type ImpressionMeta = {
  listingId: string;
  position: number;
  surface: ImpressionSurface;
  sort: string;
};

// One event carries up to this many impressions (parallel arrays). Also
// the eager-flush trigger — a fast scroll flushes at 10 rather than
// waiting out the debounce.
export const IMPRESSION_BATCH = 10;
// Idle window after the last impression before a partial batch flushes.
const FLUSH_DEBOUNCE_MS = 1000;
const VISIBILITY_THRESHOLD = 0.5;

type Buffer = { ids: string[]; positions: number[]; sort: string };

let observer: IntersectionObserver | null = null;
let observerUnavailable = false;
const metaByEl = new WeakMap<Element, ImpressionMeta>();
const fired = new Set<string>();
const buffers = new Map<ImpressionSurface, Buffer>();
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function key(surface: ImpressionSurface, listingId: string): string {
  return `${surface}:${listingId}`;
}

function ensureObserver(): IntersectionObserver | null {
  if (observer || observerUnavailable) return observer;
  if (typeof IntersectionObserver === "undefined") {
    observerUnavailable = true;
    return null;
  }
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const meta = metaByEl.get(entry.target);
        // Once seen, stop observing regardless — the element won't fire
        // again this page-view (dedupe is by listing, reset externally).
        observer?.unobserve(entry.target);
        if (!meta) continue;
        const k = key(meta.surface, meta.listingId);
        if (fired.has(k)) continue;
        fired.add(k);
        record(meta);
      }
    },
    { threshold: VISIBILITY_THRESHOLD },
  );
  return observer;
}

function record(meta: ImpressionMeta): void {
  let buf = buffers.get(meta.surface);
  if (!buf) {
    buf = { ids: [], positions: [], sort: meta.sort };
    buffers.set(meta.surface, buf);
  }
  buf.ids.push(meta.listingId);
  buf.positions.push(meta.position);
  buf.sort = meta.sort; // latest sort in the batch wins
  if (buf.ids.length >= IMPRESSION_BATCH) {
    flushSurface(meta.surface);
    return;
  }
  scheduleFlush();
}

function scheduleFlush(): void {
  if (flushTimer) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    flushAll();
  }, FLUSH_DEBOUNCE_MS);
}

function flushSurface(surface: ImpressionSurface): void {
  const buf = buffers.get(surface);
  if (!buf || buf.ids.length === 0) return;
  try {
    track("browse.card_impression", {
      listing_ids: buf.ids.slice(),
      positions: buf.positions.slice(),
      surface,
      sort: buf.sort,
    });
  } catch {
    /* never let telemetry throw into a scroll handler */
  }
  buffers.set(surface, { ids: [], positions: [], sort: buf.sort });
}

function flushAll(): void {
  for (const surface of buffers.keys()) flushSurface(surface);
}

// Register a card element for impression tracking. Returns a cleanup that
// unobserves + forgets the element (call it on unmount / meta change).
export function observeCard(el: Element, meta: ImpressionMeta): () => void {
  const obs = ensureObserver();
  if (!obs) return () => {};
  metaByEl.set(el, meta);
  obs.observe(el);
  return () => {
    obs.unobserve(el);
    metaByEl.delete(el);
  };
}

// Called by a list surface when its result identity changes (sort or
// filters). Flushes any pending impressions for that surface, then clears
// its dedupe set so cards can count again under the new ordering.
export function resetImpressions(surface: ImpressionSurface): void {
  flushSurface(surface);
  for (const k of [...fired]) {
    if (k.startsWith(`${surface}:`)) fired.delete(k);
  }
}

// React ref-callback hook for a card. Attach the returned callback to the
// card's root element:  <article ref={useCardImpression(meta)}>. When meta
// is null (surface opts out of impressions), it's a no-op ref. The
// callback re-registers if any impression field changes and cleans up on
// unmount.
export function useCardImpression(
  meta: ImpressionMeta | null,
): (el: Element | null) => void {
  const cleanupRef = useRef<(() => void) | null>(null);
  const listingId = meta?.listingId;
  const position = meta?.position;
  const surface = meta?.surface;
  const sort = meta?.sort;
  return useCallback(
    (el: Element | null) => {
      if (cleanupRef.current) {
        cleanupRef.current();
        cleanupRef.current = null;
      }
      if (el && listingId != null && position != null && surface && sort != null) {
        cleanupRef.current = observeCard(el, { listingId, position, surface, sort });
      }
    },
    [listingId, position, surface, sort],
  );
}

// Flush the tail when the tab is backgrounded/closed so we don't lose a
// partial batch. Registered once at module load; harmless off-browser.
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushAll();
  });
}

// Test-only: reset all module state so unit tests are hermetic.
export function __resetForTest(): void {
  observer = null;
  observerUnavailable = false;
  fired.clear();
  buffers.clear();
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
}
