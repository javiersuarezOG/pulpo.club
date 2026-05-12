// Internal — the lazy boundary for the Clerk SDK.
//
// Importing this file pulls in @clerk/react. clerk-shell.jsx loads it
// via React.lazy so the SDK ships in its own chunk (`clerk-bundle.js`)
// that only fetches when `clerkEnabled()` is true (publishable key set,
// VITE_USE_CLERK not "0"). See clerk-shell.jsx for the full gate.
//
// Don't import from here directly elsewhere — go through ClerkShell.
//
// Two bridges live inside <ClerkProvider>:
//
//   ClerkUserSync — maps Clerk's user to App's `setUser` so every
//                   `app.user` reader keeps working unchanged. (PR-9b)
//
//   ClerkActionsBinder — gathers openSignIn / openSignUp / signOut from
//                        useClerk() and hands them up to App via
//                        `onClerkActions`. App can then trigger Clerk's
//                        hosted modal imperatively, *without* needing a
//                        click-time Suspense boundary in SignupModal.
//                        Fixes React error #426 ("suspended in response
//                        to synchronous input"). (PR-9c hotfix)

import { useEffect } from "react";
import { ClerkProvider, useUser, useClerk } from "@clerk/react";

function planFromMetadata(metadata) {
  // Clerk Dashboard test users carry plan in publicMetadata.plan.
  // Default to "free" — pro is opt-in per user.
  const v = metadata && metadata.plan;
  return v === "pro" ? "pro" : "free";
}

function ClerkUserSync({ setUser }) {
  const { isSignedIn, user, isLoaded } = useUser();
  useEffect(() => {
    // Wait for Clerk to hydrate before touching state — otherwise we
    // briefly clear the localStorage-restored user on first paint.
    if (!isLoaded) return;
    if (!isSignedIn || !user) {
      setUser(null);
      return;
    }
    setUser({
      email:    user.primaryEmailAddress ? user.primaryEmailAddress.emailAddress : "",
      name:     user.firstName || user.username || "",
      plan:     planFromMetadata(user.publicMetadata),
      joined:   user.createdAt ? +new Date(user.createdAt) : Date.now(),
      provider: "clerk",
      clerkId:  user.id,
      // Open profile dict (see web/app/lib/user-profile.ts). Read-only
      // hydration today — PR-C wires the write path so Clerk becomes
      // the cross-device source of truth.
      profile:  (user.publicMetadata && user.publicMetadata.profile && typeof user.publicMetadata.profile === "object")
        ? user.publicMetadata.profile
        : {},
    });
  }, [isLoaded, isSignedIn, user, setUser]);
  return null;
}

function ClerkActionsBinder({ onActions }) {
  const clerk = useClerk();
  useEffect(() => {
    if (typeof onActions !== "function") return;
    onActions({
      openSignIn: (opts) => clerk.openSignIn(opts || {}),
      openSignUp: (opts) => clerk.openSignUp(opts || {}),
      signOut:    (opts) => clerk.signOut(opts || {}),
      // Synchronous "does Clerk think a user is signed in right now?"
      // SignupModal uses this to short-circuit the open call during the
      // boot race where Clerk's session is hydrated from cookies *before*
      // ClerkUserSync pushes setUser into App. Without this, we'd try
      // to open the hosted SignIn modal — Clerk knows you're signed in,
      // throws `cannot_render_single_session_enabled`, ErrorBoundary
      // catches it. `clerk.session` populates as soon as Clerk hydrates,
      // earlier than the reactive `useUser()` propagation.
      isSignedIn: () => !!clerk.session || !!clerk.user,
      // Opens Clerk's hosted UserProfile modal — that single modal
      // covers password change, email/phone management, MFA, active
      // sessions, connected OAuth accounts, and account deletion.
      // Account → Security calls this when Clerk is enabled instead
      // of mounting the dead local password form.
      openUserProfile: (opts) => clerk.openUserProfile(opts || {}),
      // Persists a profile patch through the backend. Frontend SDK
      // can't write `publicMetadata` directly (Clerk blocks it — the
      // user can't be trusted to set their own plan / preferences),
      // so we POST to /api/clerk/update-profile, which uses the
      // server-side secret key. Caller (app.updateUserProfile) does
      // the optimistic local update first and rolls back on the
      // returned promise rejection.
      //
      // Returns a promise resolving to the merged profile object on
      // success, rejecting with an Error on any failure (network,
      // auth, server). Same-origin fetch → Clerk session cookie
      // accompanies the request automatically; no manual token
      // handling required.
      updateProfile: async (patch) => {
        const res = await fetch("/api/clerk/update-profile", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ patch: patch || {} }),
        });
        if (!res.ok) {
          let detail = null;
          try { detail = await res.json(); } catch { /* keep null */ }
          const err = new Error(
            (detail && detail.error) || `update_profile_failed_${res.status}`,
          );
          err.status = res.status;
          err.code = detail && detail.error;
          throw err;
        }
        const data = await res.json();
        return data && data.profile;
      },
    });
    return () => onActions(null);
  }, [clerk, onActions]);
  return null;
}

export default function ClerkProviderWrapper({ setUser, onClerkActions, children }) {
  // <ClerkProvider> reads VITE_CLERK_PUBLISHABLE_KEY from import.meta.env.
  return (
    <ClerkProvider afterSignOutUrl="/">
      {typeof setUser === "function" ? <ClerkUserSync setUser={setUser} /> : null}
      {typeof onClerkActions === "function" ? <ClerkActionsBinder onActions={onClerkActions} /> : null}
      {children}
    </ClerkProvider>
  );
}
