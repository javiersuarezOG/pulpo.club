// PR-9a/9b — Clerk scaffolding behind a flag.
//
// `<ClerkShell>` is a pass-through wrapper that mounts `<ClerkProvider>`
// only when both VITE_USE_CLERK=1 AND a publishable key is present.
// In every other case it renders children unchanged, so today's prod
// (flag off) is byte-for-byte the same as before.
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
  return (
    import.meta.env.VITE_USE_CLERK === "1" &&
    typeof import.meta.env.VITE_CLERK_PUBLISHABLE_KEY === "string" &&
    import.meta.env.VITE_CLERK_PUBLISHABLE_KEY.length > 0
  );
}

export function ClerkShell({ setUser, children }) {
  if (!clerkEnabled()) return children;
  // Suspense fallback renders the children directly while Clerk loads,
  // so the app is interactive immediately — Clerk just hydrates auth
  // state on top once its chunk arrives.
  return (
    <Suspense fallback={children}>
      <ClerkProviderLazy setUser={setUser}>{children}</ClerkProviderLazy>
    </Suspense>
  );
}

export const __clerkScaffoldingActive = clerkEnabled;
