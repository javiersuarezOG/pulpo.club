// Filter ↔ URL serializer. Round-trips the BrowsePage filter shape
// through URLSearchParams so the browser back button, refresh, and
// shared links all reproduce the same view.
//
// Keys (legacy):
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
//
// Keys (rewrite Phase 5B — new IA axes):
//   master           — "beach" | "lake" (single-select)
//   sub              — "homes" | "condos" | "land" (single-select)
//   tag              — comma-separated discovery tags
//                      (top_rated, under_250k, gated, waterfront)

import type { DiscoveryTag, MasterCategory, Subcategory } from "./types";

const VALID_MASTER: ReadonlySet<MasterCategory>  = new Set(["beach", "lake"]);
const VALID_SUB:    ReadonlySet<Subcategory>     = new Set(["homes", "condos", "land"]);
const VALID_TAGS:   ReadonlySet<DiscoveryTag>    = new Set([
  "top_rated", "under_250k", "gated", "waterfront",
]);

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
  // Rewrite Phase 5B — new IA filter axes. null = "all" for the
  // single-selects. discovery_tags is multi-select.
  master_category: MasterCategory | null;
  subcategory: Subcategory | null;
  discovery_tags: Set<DiscoveryTag>;
  // Quality-gate inverse toggle. Default false → incomplete listings
  // are hidden. URL key: `inc=1` to opt in. The 0/absent value is
  // intentionally the same so /browse without any query maintains
  // the default-hide semantic.
  include_incomplete: boolean;
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

function parseMaster(value: string | null): MasterCategory | null {
  if (!value) return null;
  return VALID_MASTER.has(value as MasterCategory) ? (value as MasterCategory) : null;
}

function parseSub(value: string | null): Subcategory | null {
  if (!value) return null;
  return VALID_SUB.has(value as Subcategory) ? (value as Subcategory) : null;
}

function parseTags(value: string | null): Set<DiscoveryTag> {
  const raw = parseSet(value);
  const out = new Set<DiscoveryTag>();
  raw.forEach((t) => {
    if (VALID_TAGS.has(t as DiscoveryTag)) out.add(t as DiscoveryTag);
  });
  return out;
}

export function readFilterFromURL(search: string, baseDefaults: FilterShape): FilterShape {
  const p = new URLSearchParams(search);
  // master/sub/tag from URL win over the baseDefaults values when
  // present. The baseDefaults already carry any preset injected by
  // buildFiltersForCategory (legacy cat= slug expansion), so we OR
  // them in: explicit URL wins, otherwise the preset stands.
  const masterFromUrl = parseMaster(p.get("master"));
  const subFromUrl    = parseSub(p.get("sub"));
  const tagsFromUrl   = parseTags(p.get("tag"));
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
    master_category: masterFromUrl ?? baseDefaults.master_category,
    subcategory:     subFromUrl    ?? baseDefaults.subcategory,
    discovery_tags:  tagsFromUrl.size > 0 ? tagsFromUrl : baseDefaults.discovery_tags,
    include_incomplete: p.get("inc") === "1" ? true : baseDefaults.include_incomplete,
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
  // Rewrite Phase 5B — new IA axes. Single-selects omitted when null;
  // tags omitted when empty.
  setOrRemove("master", filters.master_category ?? "");
  setOrRemove("sub",    filters.subcategory ?? "");
  setOrRemove("tag",    [...filters.discovery_tags].join(","));
  setOrRemove("inc",    filters.include_incomplete ? "1" : "");
  const qs = p.toString();
  const url = `${window.location.pathname}${qs ? `?${qs}` : ""}`;
  history.replaceState({}, "", url);
}
