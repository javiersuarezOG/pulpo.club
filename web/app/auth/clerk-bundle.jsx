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
import { esMX, enUS } from "@clerk/localizations";
import { applyFounderPlan } from "../lib/founder-emails";
import { deriveSubscriptionState } from "../lib/subscription";

function planFromMetadata(metadata) {
  // Clerk Dashboard test users carry plan in publicMetadata.plan.
  // Default to "free" — pro is opt-in per user. The founder-email
  // allowlist is applied downstream in applyFounderPlan so the
  // override travels with the hydrated user object.
  const v = metadata && metadata.plan;
  return v === "pro" ? "pro" : "free";
}

// Subscription lifecycle fields written by api/stripe/webhook.js
// (see api/_plan.js for the canonical schema + grace logic). Surfaced
// onto app.user so the Account page can render the past_due grace
// banner without an extra fetch. Defaults to "active" + no grace for
// users who pre-date this field set.
function subscriptionFromMetadata(metadata) {
  const m = metadata || {};
  return {
    subscription_status:
      m.subscription_status === "past_due" || m.subscription_status === "canceled"
        ? m.subscription_status
        : "active",
    payment_failed_at: typeof m.payment_failed_at === "number" ? m.payment_failed_at : null,
    grace_period_ends_at: typeof m.grace_period_ends_at === "number" ? m.grace_period_ends_at : null,
  };
}

function ClerkUserSync({ setUser, setAuthLoaded }) {
  const { isSignedIn, user, isLoaded } = useUser();
  // Surface Clerk's `isLoaded` to App as soon as it flips, independent
  // of `setUser`. WelcomeModal gates its mount on this so the anon
  // variant doesn't flash during the post-invitation hydration race.
  // Wired separately because `setUser(null)` for an anon user is a
  // *valid* end-state — App can't distinguish "Clerk hasn't hydrated"
  // from "Clerk hydrated and confirmed no session" by looking at
  // `app.user` alone.
  useEffect(() => {
    if (typeof setAuthLoaded === "function") setAuthLoaded(!!isLoaded);
  }, [isLoaded, setAuthLoaded]);
  useEffect(() => {
    // Wait for Clerk to hydrate before touching state — otherwise we
    // briefly clear the localStorage-restored user on first paint.
    if (!isLoaded) return;
    if (!isSignedIn || !user) {
      setUser(null);
      return;
    }
    const rawPlan = planFromMetadata(user.publicMetadata);
    const subFields = subscriptionFromMetadata(user.publicMetadata);
    // Effective plan honors the 14-day grace window: a past_due user
    // with an expired grace_period_ends_at reads as "free" everywhere
    // downstream (isPaid, SiteHeader Pro pill, BottomNav star, Plans
    // page Pro state). The Account page reads subscription_status +
    // grace_period_ends_at off the same hydrated user to render the
    // grace banner with raw lifecycle context.
    const effective = deriveSubscriptionState({ plan: rawPlan, ...subFields }).effective;
    setUser(applyFounderPlan({
      email:    user.primaryEmailAddress ? user.primaryEmailAddress.emailAddress : "",
      name:     user.firstName || user.username || "",
      plan:     effective,
      joined:   user.createdAt ? +new Date(user.createdAt) : Date.now(),
      provider: "clerk",
      clerkId:  user.id,
      // Subscription lifecycle (status / grace bookkeeping). Spread
      // here so deriveSubscriptionState() can read everything off
      // app.user without an extra `user.subscription.` namespace.
      ...subFields,
      // Open profile dict (see web/app/lib/user-profile.ts). Read-only
      // hydration today — PR-C wires the write path so Clerk becomes
      // the cross-device source of truth.
      profile:  (user.publicMetadata && user.publicMetadata.profile && typeof user.publicMetadata.profile === "object")
        ? user.publicMetadata.profile
        : {},
    }));
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
      // Reads Clerk's signUp resource state — populated when the user
      // has accepted an invitation ticket but hasn't completed sign-up
      // (e.g. password not set). The `/v1/tickets/accept` redirect from
      // the activation email leaves Clerk in this in-between state:
      // not anon, not fully signed in. Returns a small descriptor so
      // app.jsx can route the user into the password-creation modal
      // without poking at Clerk's internal resource shape.
      //
      // status === "missing_requirements" + missingFields containing
      // "password" is the canonical "needs to finish sign-up" signal.
      // Returns null when there's no pending sign-up (anonymous OR
      // fully signed in).
      pendingSignUp: () => {
        const s = clerk.signUp;
        if (!s) return null;
        if (s.status !== "missing_requirements") return null;
        return {
          status: s.status,
          emailAddress: s.emailAddress || null,
          missingFields: Array.isArray(s.missingFields) ? s.missingFields : [],
        };
      },
      // Explicit two-step ticket consume — handover §7b. Clerk's SDK
      // implicit consumption from URL (just calling openSignUp with
      // __clerk_ticket in URL) didn't reliably bind the SignUp resource
      // to the ticket — Clerk's modal rendered "This ticket is invalid"
      // even on fresh tickets in some sessions. Calling signUp.create
      // with strategy="ticket" first guarantees the SignUp resource is
      // attached to the ticket BEFORE openSignUp mounts the modal, so
      // the modal renders the password step directly.
      //
      // Returns { ok: true, status, emailAddress } on success, or
      // { ok: false, code, message } on failure. Failure does NOT throw
      // — caller fires telemetry and falls through to openSignUp; Clerk's
      // hosted modal renders its own ticket-invalid alert with a "sign in
      // instead" footer, which is the right recovery UX for already-spent
      // tickets.
      consumeTicket: async (ticket) => {
        const s = clerk.signUp;
        if (!s) return { ok: false, code: "sdk_not_ready", message: "Clerk SDK not ready" };
        try {
          const result = await s.create({ strategy: "ticket", ticket });
          return {
            ok: true,
            status: result.status || s.status || null,
            emailAddress: result.emailAddress || s.emailAddress || null,
          };
        } catch (err) {
          const errors = err && err.errors;
          const first = Array.isArray(errors) && errors.length ? errors[0] : null;
          return {
            ok: false,
            code: (first && first.code) || (err && err.code) || "unknown",
            message: (first && first.longMessage) || (first && first.message) || (err && err.message) || "",
          };
        }
      },
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

export default function ClerkProviderWrapper({ setUser, setAuthLoaded, onClerkActions, locale, children }) {
  // <ClerkProvider> reads VITE_CLERK_PUBLISHABLE_KEY from import.meta.env.
  //
  // localization matches the app's pulpo-locale so Clerk's hosted modals
  // (SignIn / SignUp / UserProfile) render in the same language as the
  // surrounding app. Without this, Clerk defaults to enUS regardless of
  // user locale — a user navigating in Spanish would get the activation
  // email in Spanish, click through, and see Clerk's password modal in
  // English. esMX picked over esES because Pulpo's Spanish copy is
  // Salvadoran/Central American (closer to LATAM Spanish than Castilian).
  const localization = locale === "es" ? esMX : enUS;
  return (
    <ClerkProvider afterSignOutUrl="/" localization={localization}>
      {typeof setUser === "function" ? <ClerkUserSync setUser={setUser} setAuthLoaded={setAuthLoaded} /> : null}
      {typeof onClerkActions === "function" ? <ClerkActionsBinder onActions={onClerkActions} /> : null}
      {children}
    </ClerkProvider>
  );
}
