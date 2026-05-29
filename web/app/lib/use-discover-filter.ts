// P2a — Discover filter persistence to Clerk publicMetadata.
//
// Two pieces, designed to slot into BrowsePage with minimal blast
// radius on its existing useState / URL-sync logic:
//
//   1. `getDiscoverFilterSeed(app, hasUrlFilters)` — called from
//      useState's lazy initializer to merge the persisted Clerk
//      filter into the default seed when the URL doesn't already
//      carry one. URL params win when present (shared links stay
//      shareable); otherwise Clerk wins; otherwise defaults.
//
//   2. `useDiscoverFilterPersist(app, filter)` — effect-shaped
//      hook that mirrors filter changes back to Clerk via the
//      existing `app.updateUserProfile` action. Debounced so a
//      slider drag doesn't fire on every tick, and skipped when
//      the new value matches what's already persisted (a no-op
//      URL parse on popstate shouldn't burn a Clerk write).
//
// Anonymous users get null from getSeed (BrowsePage falls back to
// defaults) and useDiscoverFilterPersist is a no-op. localStorage
// fallback for anon → signed-in promotion is out of scope for P2a;
// it lands when the auth handoff in clerk-bundle.jsx is extended.

import { useEffect, useRef } from "react";
import {
  discoverFilterEqual,
  discoverToStorage,
  readDiscoverFilter,
  storageToDiscover,
  type DiscoverFilter,
  type DiscoverInMemoryFilter,
} from "./user-profile";

// Minimal shape of the `app` object the hook depends on. Avoids a
// circular import on app.jsx's full prop type.
type DiscoverFilterApp = {
  user: { profile?: unknown } | null | undefined;
  updateUserProfile: (patch: { discover_filters: DiscoverFilter }) => void;
};

// Returns the persisted Discover filter for the current user as an
// in-memory seed, OR null when the URL already carries filter params
// (the URL wins so shared links stay shareable). Anonymous users with
// no Clerk record also return null.
//
// `hasUrlFilters` is computed by BrowsePage's existing
// `readFilterFromURL` helper — we don't re-parse the search string
// here to avoid drift on which params count as "filter".
export function getDiscoverFilterSeed(
  app: Pick<DiscoverFilterApp, "user"> | null | undefined,
  hasUrlFilters: boolean,
): DiscoverInMemoryFilter | null {
  if (hasUrlFilters) return null;
  if (!app || !app.user) return null;
  const stored = readDiscoverFilter(app.user);
  if (!stored || Object.keys(stored).length === 0) return null;
  return storageToDiscover(stored);
}

// Default debounce. 800ms balances "doesn't burn a write on every
// toggle in a multi-chip click burst" against "the user closes the
// tab and the last change still lands." Override via the optional
// `debounceMs` param if a caller (e.g. /account/newsletter Save
// button) wants an explicit flush.
export const DEFAULT_DEBOUNCE_MS = 800;

// Pure decision helper. Returns the payload to write (after the
// debounce window) or null when the write should be skipped. Extracted
// from the hook so its logic is unit-testable without React.
//
//   `lastWritten` — the JSON-serialised last successful write payload
//                   (kept in a ref by the hook). null on first call.
//   `persisted`   — what Clerk already has on the user's profile.
//   `candidate`   — the storage-shape projection of the current filter.
//
// Returns null when:
//   • anonymous user (caller checks via `app.user`)
//   • candidate matches `lastWritten` (avoids re-firing after the
//     setUser-triggered re-render brings the same value back)
//   • candidate matches what's already persisted (mount-time
//     hydration + popstate URL reparse should never fire a write)
//
// Otherwise returns `candidate` for the hook to ship to
// app.updateUserProfile after the debounce window.
export function nextWriteForFilter(
  persisted: DiscoverFilter,
  candidate: DiscoverFilter,
  lastWritten: string | null,
): DiscoverFilter | null {
  const candidateJson = JSON.stringify(candidate);
  if (lastWritten === candidateJson) return null;
  if (discoverFilterEqual(candidate, persisted)) return null;
  return candidate;
}

// Persists filter changes to Clerk publicMetadata.profile.discover_filters.
// No-op when there's no user (anon) and no-op when the storage-shape
// projection of `filter` matches what's already persisted (skips the
// round-trip on mount-time hydration + popstate URL reparse).
export function useDiscoverFilterPersist(
  app: DiscoverFilterApp | null | undefined,
  filter: DiscoverInMemoryFilter | null | undefined,
  options?: { debounceMs?: number },
): void {
  const debounceMs = options?.debounceMs ?? DEFAULT_DEBOUNCE_MS;
  const lastWrittenRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!app || !app.user || !filter) return;
    const candidate = discoverToStorage(filter);
    const persisted = readDiscoverFilter(app.user);
    const payload = nextWriteForFilter(persisted, candidate, lastWrittenRef.current);
    if (!payload) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      lastWrittenRef.current = JSON.stringify(payload);
      app.updateUserProfile({ discover_filters: payload });
    }, debounceMs);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // Re-runs on app.user identity changes — post-Clerk hydration
    // delivers a new user object with the persisted filter already
    // set; the `discoverFilterEqual` early-return then catches it as
    // a no-op write.
  }, [app, filter, debounceMs]);
}
