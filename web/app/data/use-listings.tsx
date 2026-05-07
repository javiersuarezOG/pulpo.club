// useListings — single hook + Context provider that components consume
// to access the live listings array. Loading/error states are surfaced
// alongside the data so pages can render skeletons + retry CTAs.
//
// Mock fallback: in `vite dev` only, if the fetch fails, fall back to
// the prototype's hardcoded LISTINGS so dev-time work isn't gated on
// the data being reachable. In production, fetch failure surfaces a
// hard error UI (handled by ErrorBoundary + the page-level loader).

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { loadListings, clearListingsCache } from "./listings";
import type { Listing } from "./types";
import { track } from "../telemetry/hook";
import { LISTINGS as MOCK_LISTINGS } from "../data.jsx";

type State =
  | { status: "loading" }
  | { status: "ready"; listings: Listing[] }
  | { status: "error"; error: Error };

const ListingsCtx = createContext<{
  state: State;
  reload: () => void;
}>({
  state: { status: "loading" },
  reload: () => {},
});

export function ListingsProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);

  const reload = useCallback(() => {
    clearListingsCache();
    setReloadKey((k) => k + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    loadListings()
      .then((listings) => {
        if (!cancelled) setState({ status: "ready", listings });
      })
      .catch((err: Error) => {
        if (cancelled) return;
        track("data.fetch.failed", {
          stage: "load_listings",
          error_class: err.name || "Error",
        });
        if (import.meta.env.DEV) {
          // Dev-only fallback to the prototype's mock data so local
          // work isn't gated on the network.
          console.warn(
            "[pulpo] live data fetch failed; falling back to mock LISTINGS (dev mode only)",
            err
          );
          setState({ status: "ready", listings: MOCK_LISTINGS as Listing[] });
        } else {
          setState({ status: "error", error: err });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const value = useMemo(() => ({ state, reload }), [state, reload]);
  return <ListingsCtx.Provider value={value}>{children}</ListingsCtx.Provider>;
}

export function useListingsState() {
  return useContext(ListingsCtx);
}

// Convenience: returns just the listings array (or empty array while
// loading / error). Components that need granular states use
// useListingsState() instead.
export function useListings(): Listing[] {
  const { state } = useContext(ListingsCtx);
  return state.status === "ready" ? state.listings : [];
}
