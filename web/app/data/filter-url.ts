// Filter <-> URL serializer.
//
// The READ side moved to shared/engine/params.ts so /api/v1/listings
// parses the exact same query dialect the website emits in share links
// — see that file's header. It is re-exported here so every existing
// import in web/app keeps working.
//
// The WRITE side stays below: it touches window.history, which only
// exists in a browser.

import type { FilterShape } from "../../../shared/engine/params";
import { FILTER_URL_KEYS } from "../../../shared/engine/params";

export type { FilterShape } from "../../../shared/engine/params";
export {
  FILTER_URL_KEYS,
  PRICE_HISTO_MAX,
  hasFilterParamsInURL,
  readFilterFromURL,
  readSortFromURL,
  readViewFromURL,
} from "../../../shared/engine/params";

export type Bbox = { minLat: number; minLng: number; maxLat: number; maxLng: number };

export function readBboxFromURL(search: string): Bbox | null {
  const raw = new URLSearchParams(search).get("bbox");
  if (!raw) return null;
  const tokens = raw.split(",");
  if (tokens.length !== 4 || tokens.some((s) => s.trim() === "")) return null;
  const parts = tokens.map((s) => Number(s));
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) return null;
  const [minLat, minLng, maxLat, maxLng] = parts;
  if (minLat >= maxLat || minLng >= maxLng) return null;
  return { minLat, minLng, maxLat, maxLng };
}

export function writeBboxToURL(bbox: Bbox | null, history: History = window.history) {
  const p = new URLSearchParams(window.location.search);
  if (bbox) {
    const r = (n: number) => n.toFixed(4);
    p.set("bbox", `${r(bbox.minLat)},${r(bbox.minLng)},${r(bbox.maxLat)},${r(bbox.maxLng)}`);
  } else {
    p.delete("bbox");
  }
  const qs = p.toString();
  history.replaceState({}, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
}

export function writeFilterToURL(
  filters: FilterShape,
  category: string | null,
  sort: string,
  view: string = "cards",
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
  setOrRemove("smax", filters.size_max != null ? String(filters.size_max) : "");
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
  setOrRemove("rmax",   filters.rank_max != null && filters.rank_max > 0 ? String(filters.rank_max) : "");
  setOrRemove("inc",    filters.include_incomplete ? "1" : "");
  setOrRemove("q",      (filters.query ?? "").trim());
  // View — omitted when "cards" (the default) so plain links stay clean.
  setOrRemove("view",   view && view !== "cards" ? view : "");
  const qs = p.toString();
  const url = `${window.location.pathname}${qs ? `?${qs}` : ""}`;
  history.replaceState({}, "", url);
}
