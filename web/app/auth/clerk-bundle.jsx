// Internal — the lazy boundary for the Clerk SDK.
//
// Importing this file pulls in @clerk/react. clerk-shell.jsx loads it
// via React.lazy so the SDK ships in its own chunk (`clerk-bundle.js`)
// that only fetches when VITE_USE_CLERK=1 + a publishable key is set.
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
