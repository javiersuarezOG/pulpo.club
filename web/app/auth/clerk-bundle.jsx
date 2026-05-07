// Internal — the lazy boundary for the Clerk SDK.
//
// Importing this file pulls in @clerk/react. clerk-shell.jsx loads it
// via React.lazy so the SDK ships in its own chunk (`clerk-bundle.js`)
// that only fetches when VITE_USE_CLERK=1 + a publishable key is set.
//
// Don't import from here directly elsewhere — go through ClerkShell
// (PR-9a) and useAuthSource (PR-9b).
import { ClerkProvider } from "@clerk/react";

export default function ClerkProviderWrapper({ children }) {
  // <ClerkProvider> reads VITE_CLERK_PUBLISHABLE_KEY from import.meta.env.
  return <ClerkProvider afterSignOutUrl="/">{children}</ClerkProvider>;
}
