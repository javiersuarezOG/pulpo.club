// PR-9a/9b/9d — Clerk scaffolding behind a flag.
//
// `<ClerkShell>` is a pass-through wrapper that mounts `<ClerkProvider>`
// only when a Clerk publishable key is present *and* the explicit
// VITE_USE_CLERK=0 opt-out isn't set.
//
// Default flip (PR-9d): the env var is now opt-out rather than opt-in.
// Any deploy or local-dev env that ships a `VITE_CLERK_PUBLISHABLE_KEY`
// gets Clerk by default; setting `VITE_USE_CLERK=0` keeps the legacy
// email/password path for cases where Clerk isn't wired (CI, fresh
// clones without a key, the e2e dev server). With no publishable key,
// Clerk stays off either way — that's the safe fallback so a missing
// env var can never crash the app.
//
// Clerk is loaded via React.lazy + dynamic import so the SDK ships in
// its own chunk that only loads when the flag is on. With the flag off
// the chunk is never fetched and the main bundle stays clean.
//
// PR-9b — passes `setUser` through to the lazy bundle so a tiny
// ClerkUserSync inside ClerkProvider can map Clerk's user object to
// App's legacy `{ email, name, plan, joined }` shape and push it into
// existing state. Every downstream `app.user` reader keeps working
// unchanged.
import React, { Suspense, lazy } from "react";

// Module-level lazy: Vite/Rollup splits clerk-bundle.jsx (and its
// transitive @clerk/react import) into its own chunk that only loads
// when this lazy component is actually rendered.
const ClerkProviderLazy = lazy(() => import("./clerk-bundle.jsx"));

export function clerkEnabled() {
  // Opt-out: VITE_USE_CLERK="0" keeps the legacy auth path. Any other
  // value (including unset) means Clerk is on as long as a publishable
  // key is configured. The publishable-key check is the safety net —
  // a missing key would crash <ClerkProvider>, so we keep Clerk off in
  // that case regardless of the flag.
  if (import.meta.env.VITE_USE_CLERK === "0") return false;
  return (
    typeof import.meta.env.VITE_CLERK_PUBLISHABLE_KEY === "string" &&
    import.meta.env.VITE_CLERK_PUBLISHABLE_KEY.length > 0
  );
}

export function ClerkShell({ setUser, setAuthLoaded, onClerkActions, children }) {
  if (!clerkEnabled()) return children;
  // Suspense fallback renders the children directly while Clerk loads,
  // so the app is interactive immediately — Clerk just hydrates auth
  // state on top once its chunk arrives. This Suspense fires once on
  // boot, *not* in response to user input — that's the one #426 trap
  // we have to avoid (see SignupModal in pages.jsx).
  //
  // setAuthLoaded mirrors setUser: passed through to ClerkUserSync so
  // App can know when Clerk has finished hydrating (isLoaded === true)
  // and the modal-gate in WelcomeModal can stop showing the anon
  // variant during the hydration race.
  return (
    <Suspense fallback={children}>
      <ClerkProviderLazy
        setUser={setUser}
        setAuthLoaded={setAuthLoaded}
        onClerkActions={onClerkActions}
      >
        {children}
      </ClerkProviderLazy>
    </Suspense>
  );
}

export const __clerkScaffoldingActive = clerkEnabled;
