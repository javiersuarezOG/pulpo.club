// useDebouncedValue — defers updates by `delay` ms. Used in BrowsePage
// to debounce `applyFilters()` against slider drags so a single drag
// fires one re-filter at the end instead of dozens.
//
// Filter chip toggles bypass this (set the same `filters` reference
// shape; debouncing wraps it for the memo input).

import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}
