// Guarded localStorage access.
//
// Safari with "Block all cookies" (and some in-app webviews / private
// modes) throws `SecurityError` on ANY localStorage access — including a
// bare `.getItem`. An unguarded read inside a `useState` initializer or
// render body therefore throws DURING render, which the root ErrorBoundary
// catches by blanking the entire app ("Something went wrong."). Persistence
// is a convenience here, never a contract, so every access degrades to a
// no-op / fallback instead of crashing.
//
// Use these at every render-path or effect localStorage site in web/app/.
// (The inline try/catch sites that predate this helper are equivalent;
// new code should prefer the helper so the intent is obvious.)

export function safeLocalGet(key: string): string | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function safeLocalSet(key: string, value: string): void {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(key, value);
  } catch {
    /* storage blocked / quota — best effort, never throw */
  }
}

export function safeLocalRemove(key: string): void {
  try {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(key);
  } catch {
    /* storage blocked — best effort, never throw */
  }
}
