// Filter ↔ URL serializer. Round-trips the BrowsePage filter shape
// through URLSearchParams so the browser back button, refresh, and
// shared links all reproduce the same view.
//
// Keys:
//   cat              — pill / category (drives the rest)
//   zones            — comma-separated zone names
//   types            — comma-separated land types
//   features         — comma-separated key features (beachfront,…)
//   infra            — comma-separated infrastructure (water,…)
//   status           — comma-separated listing status (new,…)
//   pmin / pmax      — price bounds (numeric)
//   smin             — size minimum (numeric)
//   ready            — readiness floor (0–4)
//   score_min        — score floor (0–100)
//   wv / wl / wm     — Value / Location / Momentum weight (0–100)
//   sort             — sort key

export type FilterShape = {
  zones: Set<string>;
  land_types: Set<string>;
  features: Set<string>;
  infra: Set<string>;
  status: Set<string>;
  price_min: number;
  price_max: number | null;   // null = no upper cap (default; was 1,000,000 — hid ~20% of catalog)
  size_min: number;
  readiness: number;
  score_min?: number;
  weights?: { value: number; location: number; momentum: number };
};

// Visual scale for the price histogram. Listings above this still pass
// the filter (when price_max is null) — they just cluster in the
// rightmost bucket of the bar chart.
export const PRICE_HISTO_MAX = 1_000_000;

function parseSet(value: string | null): Set<string> {
  if (!value) return new Set();
  return new Set(value.split(",").map((s) => s.trim()).filter(Boolean));
}

function parseInt0(value: string | null, fallback: number): number {
  if (value == null) return fallback;
  const n = parseInt(value, 10);
  return Number.isFinite(n) ? n : fallback;
}

export function readFilterFromURL(search: string, baseDefaults: FilterShape): FilterShape {
  const p = new URLSearchParams(search);
  const out: FilterShape = {
    ...baseDefaults,
    zones: parseSet(p.get("zones")),
    land_types: parseSet(p.get("types")),
    features: parseSet(p.get("features")),
    infra: parseSet(p.get("infra")),
    status: parseSet(p.get("status")),
    price_min: parseInt0(p.get("pmin"), 0),
    price_max: p.get("pmax") != null ? parseInt0(p.get("pmax"), 0) : null,
    size_min: parseInt0(p.get("smin"), 0),
    readiness: parseInt0(p.get("ready"), 0),
  };
  const sm = p.get("score_min");
  if (sm != null) out.score_min = parseInt0(sm, 0);
  const wv = p.get("wv");
  const wl = p.get("wl");
  const wm = p.get("wm");
  if (wv && wl && wm) {
    out.weights = {
      value: parseInt0(wv, 40),
      location: parseInt0(wl, 35),
      momentum: parseInt0(wm, 25),
    };
  }
  return out;
}

export function readSortFromURL(search: string, fallback: string): string {
  const p = new URLSearchParams(search);
  return p.get("sort") || fallback;
}

export function writeFilterToURL(
  filters: FilterShape,
  category: string | null,
  sort: string,
  history: History = window.history
) {
  const p = new URLSearchParams(window.location.search);
  // Preserve unrelated params (?dev=1, ?debug=1, utm_*).
  const setOrRemove = (key: string, value: string) => {
    if (value) p.set(key, value);
    else p.delete(key);
  };
  setOrRemove("cat", category ?? "");
  setOrRemove("zones", [...filters.zones].join(","));
  setOrRemove("types", [...filters.land_types].join(","));
  setOrRemove("features", [...filters.features].join(","));
  setOrRemove("infra", [...filters.infra].join(","));
  setOrRemove("status", [...filters.status].join(","));
  setOrRemove("pmin", filters.price_min > 0 ? String(filters.price_min) : "");
  setOrRemove("pmax", filters.price_max != null ? String(filters.price_max) : "");
  setOrRemove("smin", filters.size_min > 0 ? String(filters.size_min) : "");
  setOrRemove("ready", filters.readiness > 0 ? String(filters.readiness) : "");
  setOrRemove(
    "score_min",
    filters.score_min && filters.score_min > 0 ? String(filters.score_min) : ""
  );
  if (filters.weights) {
    setOrRemove("wv", String(filters.weights.value));
    setOrRemove("wl", String(filters.weights.location));
    setOrRemove("wm", String(filters.weights.momentum));
  } else {
    p.delete("wv");
    p.delete("wl");
    p.delete("wm");
  }
  setOrRemove("sort", sort && sort !== "recent" ? sort : "");
  const qs = p.toString();
  const url = `${window.location.pathname}${qs ? `?${qs}` : ""}`;
  history.replaceState({}, "", url);
}
