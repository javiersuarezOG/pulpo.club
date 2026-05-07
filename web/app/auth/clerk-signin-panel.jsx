// Lazy-loaded bridge to Clerk's hosted sign-in / sign-up modal.
//
// Why a bridge instead of <SignIn /> embedded in our chrome:
//   * Clerk's hosted modal handles every edge case (MFA, OAuth
//     providers, password reset, account links) without us re-skinning
//     each one.
//   * Closes itself on success, no afterSignInUrl reload needed.
//
// SignupModal (in pages.jsx) lazy-imports this when flag is on. The
// component renders nothing — it just imperatively opens Clerk's modal
// on mount, then asks the parent to dismiss our shell modal so the
// two don't stack.

import { useEffect } from "react";
import { useClerk } from "@clerk/react";

export default function ClerkSignInPanel({ mode, onClose }) {
  const clerk = useClerk();
  useEffect(() => {
    const cb = { afterSignInUrl: window.location.href, afterSignUpUrl: window.location.href };
    if (mode === "signup") clerk.openSignUp(cb);
    else clerk.openSignIn(cb);
    // Dismiss our shell modal; Clerk's hosted modal is now in front.
    if (typeof onClose === "function") onClose();
  }, [mode]);
  return null;
}
