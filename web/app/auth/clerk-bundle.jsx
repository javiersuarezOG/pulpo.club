// Internal — the lazy boundary for the Clerk SDK.
//
// Importing this file pulls in @clerk/react. clerk-shell.jsx loads it
// via React.lazy so the SDK ships in its own chunk (`clerk-bundle.js`)
// that only fetches when VITE_USE_CLERK=1 + a publishable key is set.
//
// Don't import from here directly elsewhere — go through ClerkShell.
//
// PR-9b — when a `setUser` prop is passed, also mounts <ClerkUserSync>
// inside the provider. That bridge converts Clerk's user object to the
// app's legacy `{ email, name, plan, joined }` shape and pushes it
// into App's existing state, so every downstream `app.user` reader is
// unchanged. Without `setUser` (flag off) ClerkShell never renders
// this file at all.
import { useEffect } from "react";
import { ClerkProvider, useUser } from "@clerk/react";

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

export default function ClerkProviderWrapper({ setUser, children }) {
  // <ClerkProvider> reads VITE_CLERK_PUBLISHABLE_KEY from import.meta.env.
  return (
    <ClerkProvider afterSignOutUrl="/">
      {typeof setUser === "function" ? <ClerkUserSync setUser={setUser} /> : null}
      {children}
    </ClerkProvider>
  );
}
